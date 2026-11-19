"""Otomatik doğrulama (S14): saf denetimler + klip yok / model yok yolları. GPU/model gerekmez."""
import json

from tracker import autotest as at


def test_auto_rect_lower_half_clipped():
    assert at.auto_rect((100, 100, 300, 500), (1000, 450)) == [100, 300, 300, 450]


def test_zoom_pumping_counts_reversals_not_noise():
    steady = [[t, 0.5 + 0.01 * (t % 2), 0, 0] for t in range(0, 60, 2)]
    assert at.zoom_pumping(steady)["reversals"] == 0  # adımlar eşik altı
    pump = [[t, 0.5 if (t // 2) % 2 else 0.0, 0, 0] for t in range(0, 60, 2)]
    p = at.zoom_pumping(pump)
    assert p["reversals"] > 20 and p["per_min"] > at.PUMP_PER_MIN
    assert at.zoom_pumping([[0, 0, 0, 0]]) == {"reversals": 0, "per_min": 0.0, "max_rate": 0.0}


def test_zoom_pumping_max_rate():
    assert abs(at.zoom_pumping([[0, 0, 0, 0], [2, 1.0, 0, 0]])["max_rate"] - 0.5) < 1e-9


def _doc(tracked=90, frames=100, counts=None):
    return {"counts": {"frames": frames, "tracked": tracked}, "state": {"counts": counts or {"TRACKED": tracked}},
            "gate": {"rejected": 2, "unclean": 1}}


def test_check_tracking_thresholds_and_states():
    ok = {c.name: c.status for c in at.check_tracking(_doc(), {})}
    assert ok["izlenen kare oranı"] == at.PASS
    bad = {c.name: c.status for c in at.check_tracking(_doc(tracked=40), {})}
    assert bad["izlenen kare oranı"] == at.FAIL
    exp = {"states_include": ["OUT_OF_FRAME"], "states_exclude": ["TRACKED"]}
    r = {c.name: c.status for c in at.check_tracking(_doc(), exp)}
    assert r["durum görüldü: OUT_OF_FRAME"] == at.FAIL and r["durum görülmedi: TRACKED"] == at.FAIL


def test_check_refined_frame_count_and_tracked():
    a = {"records": [0] * 10, "counts": {"tracked": 8}}
    assert all(c.status != at.FAIL for c in at.check_refined(a, {"records": [0] * 10, "counts": {"tracked": 9}}))
    r = at.check_refined(a, {"records": [0] * 9, "counts": {"tracked": 7}})
    assert [c.status for c in r[:2]] == [at.FAIL, at.FAIL]


def test_check_export_needs_exit_zero_and_validation_line():
    ok = at.Step("e", [], code=0, tail="kaydedildi\ndoğrulama: tamam")
    assert at.check_export(ok, "x").status == at.PASS
    assert at.check_export(at.Step("e", [], code=4, tail="doğrulama: tamam"), "x").status == at.FAIL
    assert at.check_export(at.Step("e", [], code=0, tail="kaydedildi"), "x").status == at.FAIL


def test_check_camera_on_still_subject():
    n = 60
    fields = ["t", "tracked", "accepted", "x1", "y1", "x2", "y2", "clean", "w", "h"]
    recs = [[i / 10, 1, 1, 0.4, 0.5, 0.6, 0.9, 1, 0.2, 0.4] for i in range(n)]
    doc = {"fields": fields, "records": recs, "video": {"w": 1280, "h": 720}, "counts": {"frames": n, "tracked": n}}
    by = {c.name: c for c in at.check_camera(doc)}
    assert by["zoom titremesi"].status == at.PASS and by["zoom hız sınırı"].status == at.PASS
    assert "doluluk (ortanca)" in by and by["kamera özeti"].status == at.INFO


def test_main_without_clips_returns_2(tmp_path, capsys):
    assert at.main(["--clips", str(tmp_path / "yok")]) == 2
    assert "video yok" in capsys.readouterr().out


def test_main_reports_failure_when_graphs_missing(tmp_path):
    (tmp_path / "k").mkdir()
    (tmp_path / "k" / "a.mp4").write_bytes(b"x")
    out = tmp_path / "o"
    code = at.main(["--clips", str(tmp_path / "k"), "--model-dir", str(tmp_path / "yok"), "--out", str(out),
                    "--device", "cpu"])
    assert code == 1  # sam-bench grafik bulamaz -> KALDI, klipler atlanır
    rep = next(out.iterdir()) / "report.json"
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["clips"] == [] and any(c["status"] == at.FAIL for c in data["pre"])
    assert (rep.parent / "report.md").read_text(encoding="utf-8").startswith("# Otomatik")


def test_run_step_missing_command_is_logged(tmp_path):
    s = at.run_step("x y", ["yok-komut-xyz"], tmp_path)
    assert s.code not in (0, None) and (tmp_path / "x_y.log").exists()


def test_file_mode_writes_log_and_md_to_out(tmp_path):
    f = tmp_path / "ders.mp4"
    f.write_bytes(b"x")
    out = tmp_path / "desk"
    code = at.main(["--file", str(f), "--model-dir", str(tmp_path / "yok"), "--out", str(out), "--device", "cpu"])
    assert code == 1
    dirs = [d for d in out.iterdir() if d.is_dir()]
    assert len(dirs) == 1 and dirs[0].name.startswith("Takipli-Test-ders-")
    assert (out / f"{dirs[0].name}.md").exists()  # masaüstünde tek dosya kopyası


def test_file_mode_missing_file_returns_2(tmp_path):
    assert at.main(["--file", str(tmp_path / "yok.mp4")]) == 2


def test_desktop_dir_exists():
    assert at.desktop_dir().is_dir()
