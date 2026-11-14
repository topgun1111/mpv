"""EdgeTAM (default) or SAM 2.1 -> two ONNX files for the Android `sam` build (CI only; Apache-2.0 code).

Usage: python scripts/export_sam2.py OUT_DIR [edgetam|base_plus|small|large]
Writes OUT_DIR/sam-encoder.onnx and OUT_DIR/sam-decoder.onnx.
Needs: pip install torch torchvision onnx + ONE of (both install a package named `sam2`, never install both together):
  edgetam:  git+https://github.com/facebookresearch/EdgeTAM.git
  others:   git+https://github.com/facebookresearch/sam2.git
EdgeTAM is a SAM 2 fork (same prompt encoder / mask decoder / build_sam2), so the same wrappers are used.

encoder: image [1,3,1024,1024] (RGB, ImageNet mean/std) -> high_res_feats_0 [1,32,256,256], high_res_feats_1 [1,64,128,128],
         image_embed [1,256,64,64]  (no_mem_embed already added: single-image mode)
decoder: image_embed, high_res_feats_0/1, point_coords [1,N,2] (1024 px space), point_labels [1,N] (1 = positive,
         0 = negative, 2 / 3 = box top-left / bottom-right), mask_input [1,1,256,256], has_mask_input [1]
         -> low_res_masks [1,3,256,256] (logits, > 0 = object), iou_predictions [1,3]
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_SAM21 = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_{}.pt"
# name -> (config candidates, checkpoint URL candidates); each list is tried in order (repo layouts differ between versions)
VARIANTS = {
    "edgetam": (["configs/edgetam.yaml", "edgetam.yaml"],
                ["https://huggingface.co/facebook/EdgeTAM/resolve/main/edgetam.pt",
                 "https://huggingface.co/yangchris11/edgetam/resolve/main/edgetam.pt"]),
    "base_plus": (["configs/sam2.1/sam2.1_hiera_b+.yaml"], [_SAM21.format("base_plus")]),
    "small": (["configs/sam2.1/sam2.1_hiera_s.yaml"], [_SAM21.format("small")]),
    "large": (["configs/sam2.1/sam2.1_hiera_l.yaml"], [_SAM21.format("large")]),
}
MIN_BYTES = 20_000_000


def main(argv: list[str]) -> int:
    import torch
    from torch import nn
    from sam2.build_sam import build_sam2

    out = Path(argv[1] if len(argv) > 1 else "sam-models")
    size = argv[2] if len(argv) > 2 else "edgetam"
    cfgs, urls = VARIANTS[size]
    out.mkdir(parents=True, exist_ok=True)
    ckpt = out / f"{size}.pt"
    for u in urls:
        if ckpt.is_file() and ckpt.stat().st_size > 1_000_000:
            break
        try:
            urllib.request.urlretrieve(u, ckpt)
        except Exception as e:  # try the next mirror
            print(f"download failed ({u}): {e}", file=sys.stderr)
    if not ckpt.is_file() or ckpt.stat().st_size < 1_000_000:
        print("ERROR: checkpoint download failed", file=sys.stderr)
        return 1
    sam, err = None, None
    for c in cfgs:
        try:
            sam = build_sam2(c, str(ckpt), device="cpu").eval()
            break
        except Exception as e:
            err = e
            print(f"build_sam2({c}) failed: {e}", file=sys.stderr)
    if sam is None:
        raise err

    class Encoder(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            o = self.m.image_encoder(x)
            fpn = o["backbone_fpn"]
            f0 = self.m.sam_mask_decoder.conv_s0(fpn[0])
            f1 = self.m.sam_mask_decoder.conv_s1(fpn[1])
            emb = fpn[2] + self.m.no_mem_embed.reshape(1, -1, 1, 1)
            return f0, f1, emb

    class Decoder(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m, self.pe, self.md = m, m.sam_prompt_encoder, m.sam_mask_decoder

        def forward(self, image_embed, high_res_feats_0, high_res_feats_1, point_coords, point_labels, mask_input, has_mask_input):
            c = point_coords + 0.5
            c = torch.cat([c, torch.zeros_like(c[:, :1])], dim=1)
            lab = torch.cat([point_labels, -torch.ones_like(point_labels[:, :1])], dim=1)
            c = c / self.m.image_size
            emb = self.pe.pe_layer._pe_encoding(c)
            lab = lab.unsqueeze(-1).expand_as(emb)
            emb = emb * (lab != -1) + self.pe.not_a_point_embed.weight * (lab == -1)
            for i in range(self.pe.num_point_embeddings):
                emb = emb + self.pe.point_embeddings[i].weight * (lab == i)
            dense = has_mask_input * self.pe.mask_downscaling(mask_input) + \
                (1 - has_mask_input) * self.pe.no_mask_embed.weight.reshape(1, -1, 1, 1)
            masks, iou, _, _ = self.md.predict_masks(
                image_embeddings=image_embed, image_pe=self.pe.get_dense_pe(), sparse_prompt_embeddings=emb,
                dense_prompt_embeddings=dense, repeat_image=False, high_res_features=[high_res_feats_0, high_res_feats_1])
            return torch.clamp(masks[:, 1:], -32.0, 32.0), iou[:, 1:]

    def export(model, args, path, inputs, outputs, dyn=None):
        kw = dict(input_names=inputs, output_names=outputs, dynamic_axes=dyn, opset_version=17, do_constant_folding=True)
        try:
            torch.onnx.export(model, args, str(path), dynamo=False, **kw)
        except TypeError:  # older torch has no `dynamo` argument
            torch.onnx.export(model, args, str(path), **kw)

    with torch.no_grad():
        o = sam.image_encoder(torch.randn(1, 3, 1024, 1024))  # shapes the Kotlin side assumes: 1024 input, 256x256 masks
        print("fpn shapes:", [tuple(f.shape) for f in o["backbone_fpn"]], "image_size:", sam.image_size)
        enc = out / "sam-encoder.onnx"
        export(Encoder(sam), (torch.randn(1, 3, 1024, 1024),), enc, ["image"], ["high_res_feats_0", "high_res_feats_1", "image_embed"])
        dec = out / "sam-decoder.onnx"
        args = (torch.randn(1, 256, 64, 64), torch.randn(1, 32, 256, 256), torch.randn(1, 64, 128, 128),
                torch.tensor([[[400.0, 400.0], [600.0, 600.0], [500.0, 500.0]]]), torch.tensor([[2.0, 3.0, 1.0]]),
                torch.zeros(1, 1, 256, 256), torch.zeros(1))
        export(Decoder(sam), args, dec, ["image_embed", "high_res_feats_0", "high_res_feats_1", "point_coords", "point_labels", "mask_input", "has_mask_input"],
               ["low_res_masks", "iou_predictions"], {"point_coords": {1: "n"}, "point_labels": {1: "n"}})
    ckpt.unlink(missing_ok=True)
    for p in (enc, dec):
        if not p.is_file() or p.stat().st_size < MIN_BYTES // 4:
            print(f"ERROR: export failed or too small: {p}", file=sys.stderr)
            return 1
        print(f"ready: {p} ({p.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
