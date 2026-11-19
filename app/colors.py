"""Главные цвета картинки - для поиска «цвет:синий» (как поиск по цвету в Eagle).

Картинка уменьшается до 32×32, каждый пиксель относится к одному из 12 понятных цветов,
и в базу записываются цвета, которые занимают заметную часть картинки.
Чтение картинки - в app/ui/thumbs.py (Qt), здесь только математика.
"""
import colorsys

# название -> цвет для кнопки-образца в интерфейсе
PALETTE = {
    "красный": "#e03131", "оранжевый": "#f76707", "жёлтый": "#fcc419", "зелёный": "#37b24d",
    "голубой": "#22b8cf", "синий": "#1c7ed6", "фиолетовый": "#7048e8", "розовый": "#e64980",
    "коричневый": "#8d5a2b", "белый": "#f8f9fa", "серый": "#868e96", "чёрный": "#212529",
}

MIN_SHARE = 0.12   # цвет должен занимать хотя бы 12% картинки
MAX_COLORS = 3


def classify(r, g, b):
    """RGB (0..255) -> название цвета из PALETTE."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if l < 0.13:
        return "чёрный"
    if l > 0.9 and s < 0.5:
        return "белый"
    if s < 0.18:
        return "серый" if l < 0.85 else "белый"
    deg = h * 360
    if deg < 12 or deg >= 345:
        return "красный"
    if deg < 40:
        return "коричневый" if l < 0.35 else "оранжевый"
    if deg < 68:
        return "жёлтый"
    if deg < 160:
        return "зелёный"
    if deg < 195:
        return "голубой"
    if deg < 255:
        return "синий"
    if deg < 290:
        return "фиолетовый"
    return "розовый"


def dominant(pixels):
    """pixels: [(r, g, b, a)] -> "синий,белый" (до 3 цветов, самые частые первыми)."""
    counts, total = {}, 0
    for r, g, b, a in pixels:
        if a < 128:  # прозрачное не считаем
            continue
        name = classify(r, g, b)
        counts[name] = counts.get(name, 0) + 1
        total += 1
    if not total:
        return ""
    top = sorted(counts.items(), key=lambda x: -x[1])
    return ",".join(name for name, n in top[:MAX_COLORS] if n / total >= MIN_SHARE)
