"""Takipli Oynat — Kayıt (recording) varyantı: yalnız elle kamera (zoom + sürükleme aynı anda).

Ana varyanttan (`tracker/`) bağımsızdır: model, takip, poz yok; ana paketi içe aktarmaz.
Anahtar kare biçimi `[t, zoom(log2), pan_x, pan_y]` ana varyant ve Android ile aynıdır.
"""

__version__ = "1.2.0"
VARIANT = "recording"
