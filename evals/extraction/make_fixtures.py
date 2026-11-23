"""Render the synthetic extraction fixtures: `uv run python -m evals.extraction.make_fixtures`.

Every name, number and ID here is fictional. Numbers use valid Cameroonian formats so the
normaliser accepts them, but they are made up. Re-run after editing, then commit the PNGs.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IMAGES_DIR = Path(__file__).resolve().parent / "images"
WIDTH = 720
PAD = 32


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def sms(path: Path, sender: str, time: str, body: str, accent: str) -> None:
    """An SMS inbox screenshot with one operator message."""
    image = Image.new("RGB", (WIDTH, 620), "#f2f2f2")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 90), fill=accent)
    draw.text((PAD, 28), sender, font=_font(34), fill="white")
    draw.text((WIDTH - 140, 36), time, font=_font(24), fill="white")
    body_font = _font(26)
    lines = _wrap(draw, body, body_font, WIDTH - 4 * PAD)
    height = 40 + 36 * len(lines)
    draw.rounded_rectangle((PAD, 130, WIDTH - PAD, 130 + height), radius=18, fill="white")
    for i, line in enumerate(lines):
        draw.text((2 * PAD, 150 + 36 * i), line, font=body_font, fill="#222222")
    image.save(path)


def chat(path: Path, contact: str, messages: list[tuple[str, str, str]]) -> None:
    """A WhatsApp-style chat. Each message is (side, text, time) with side "them" or "me"."""
    image = Image.new("RGB", (WIDTH, 1100), "#ece5dd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 100), fill="#075e54")
    draw.text((PAD, 32), contact, font=_font(34), fill="white")
    font, small = _font(25), _font(18)
    y = 130
    for side, text, time in messages:
        lines = _wrap(draw, text, font, WIDTH - 6 * PAD)
        bubble_w = max(draw.textlength(line, font=font) for line in lines) + 2 * PAD + 40
        bubble_h = 30 + 34 * len(lines) + 20
        x0 = PAD if side == "them" else WIDTH - PAD - bubble_w
        fill = "white" if side == "them" else "#dcf8c6"
        draw.rounded_rectangle((x0, y, x0 + bubble_w, y + bubble_h), radius=16, fill=fill)
        for i, line in enumerate(lines):
            draw.text((x0 + PAD, y + 15 + 34 * i), line, font=font, fill="#111111")
        draw.text((x0 + bubble_w - 70, y + bubble_h - 26), time, font=small, fill="#777777")
        y += bubble_h + 24
    image.crop((0, 0, WIDTH, min(1100, y + 20))).save(path)


def post(path: Path) -> None:
    """A marketplace-style product post."""
    image = Image.new("RGB", (WIDTH, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((PAD, 30), "Boutique Fictive Phones", font=_font(32), fill="#1877f2")
    draw.text((PAD, 76), "Il y a 3 h", font=_font(20), fill="#888888")
    draw.rectangle((PAD, 120, WIDTH - PAD, 520), fill="#d9d9d9")
    draw.text((WIDTH // 2 - 110, 300), "[ photo produit ]", font=_font(28), fill="#555555")
    text = (
        "iPhone 13 Pro 256 Go neuf sous blister, 150.000 FCFA seulement !! "
        "Livraison partout au Cameroun. Paiement d'abord par Orange Money. "
        "Contact WhatsApp : 6 99 87 65 43"
    )
    body = _font(26)
    for i, line in enumerate(_wrap(draw, text, body, WIDTH - 2 * PAD)):
        draw.text((PAD, 550 + 36 * i), line, font=body, fill="#111111")
    image.save(path)


def main() -> None:
    IMAGES_DIR.mkdir(exist_ok=True)
    sms(
        IMAGES_DIR / "momo_sms.png",
        "MobileMoney",
        "14:32",
        "Transfert de 25000 FCFA a JEAN TESTEUR (237677001122) effectue le 20/11/2026 14:32. "
        "Frais: 0 FCFA. Nouveau solde: 3500 FCFA. Transaction Id: 9900112233.",
        "#ffcc00",
    )
    sms(
        IMAGES_DIR / "om_sms.png",
        "OrangeMoney",
        "09:30",
        "Vous avez transfere 40000 FCFA vers 699001122 ALINE FICTIVE le 21/11/2026. "
        "ID: PP261121.0930.B00002. Solde: 12000 FCFA. Orange Money.",
        "#ff7900",
    )
    chat(
        IMAGES_DIR / "chat.png",
        "Vendeur Laptop",
        [
            ("me", "Bonjour, le HP EliteBook est toujours dispo ?", "10:02"),
            ("them", "Oui grand frere. 85000 frs, livraison demain a Douala.", "10:04"),
            ("them", "Envoie l'avance de 30000 sur le 650 11 22 33 stp", "10:05"),
            ("me", "Ok j'envoie maintenant", "10:11"),
            ("me", "Le livreur est ou? Ca fait 3 jours", "18:40"),
        ],
    )
    post(IMAGES_DIR / "post.png")
    chat(
        IMAGES_DIR / "combined_chat.png",
        "Jean T. Phones",
        [
            ("them", "Samsung A54 na 60000. You go pay first before I send am.", "13:50"),
            ("me", "I fit pay 25000 now, rest for delivery?", "14:01"),
            ("them", "Ok. Send am for MoMo 677 00 11 22 name Jean Testeur", "14:05"),
            ("me", "I don send. Check am", "14:33"),
            ("me", "Hello? You don block me?", "20:15"),
        ],
    )


if __name__ == "__main__":
    main()
