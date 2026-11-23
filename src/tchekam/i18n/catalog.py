"""User-facing copy. Every key has fr, en and pcm; t() falls back to French for anything missing.

Copy rules: never label a person as a scammer or fraudster (see tests/i18n/test_catalog.py).
Each pcm entry must carry a trailing "# needs native review" marker, enforced by a test.
"""

_PICKER = "Choisissez votre langue / Choose your language / Pick your language:\n1. Français\n2. English\n3. Pidgin"

CATALOG: dict[str, dict[str, str]] = {
    "lang.picker": {
        "fr": _PICKER,
        "en": _PICKER,
        "pcm": _PICKER,  # needs native review
    },
    "menu.main": {
        "fr": (
            "Que voulez-vous faire ?\n"
            "1. Vérifier un numéro\n"
            "2. Vérifier une photo\n"
            "3. Vérifier un message\n"
            "4. Signaler une arnaque\n"
            "5. Aide\n"
            "0 = menu, LANG = langue"
        ),
        "en": (
            "What would you like to do?\n"
            "1. Check a number\n"
            "2. Check a photo\n"
            "3. Check a message\n"
            "4. Report a scam\n"
            "5. Help\n"
            "0 = menu, LANG = language"
        ),
        "pcm": (
            "Wetin you want do?\n"
            "1. Check one number\n"
            "2. Check one photo\n"
            "3. Check one message\n"
            "4. Report one scam\n"
            "5. Help\n"
            "0 = menu, LANG = language"
        ),  # needs native review
    },
    "menu.welcome": {
        "fr": "Bienvenue sur Tchek-Am !",
        "en": "Welcome to Tchek-Am!",
        "pcm": "Welcome to Tchek-Am!",  # needs native review
    },
    "menu.terms": {
        "fr": "Confidentialité et conditions : {url}",
        "en": "Privacy and terms: {url}",
        "pcm": "Privacy and terms: {url}",  # needs native review
    },
    "prompt.send_number": {
        "fr": "Envoyez le numéro à vérifier (exemple : 6 77 12 34 56).",
        "en": "Send the number you want to check (example: 6 77 12 34 56).",
        "pcm": "Send di number wey you want check (example: 6 77 12 34 56).",  # needs native review
    },
    "prompt.send_photo": {
        "fr": "Envoyez la photo du produit à vérifier.",
        "en": "Send the photo of the product you want to check.",
        "pcm": "Send di photo of di product wey you want check.",  # needs native review
    },
    "prompt.send_message": {
        "fr": "Collez ici le message à vérifier.",
        "en": "Paste the message you want to check here.",
        "pcm": "Paste di message wey you want check for here.",  # needs native review
    },
    "prompt.no_number": {
        "fr": "Je ne trouve pas de numéro camerounais valide. Réessayez, ou tapez 0 pour le menu.",
        "en": "I can't find a valid Cameroonian number. Try again, or type 0 for the menu.",
        "pcm": "I no see correct Cameroon number. Try again, or type 0 for menu.",  # needs native review
    },
    "prompt.expected_photo": {
        "fr": "J'attends une photo. Envoyez-la, ou tapez 0 pour le menu.",
        "en": "I'm waiting for a photo. Send it, or type 0 for the menu.",
        "pcm": "I dey wait for photo. Send am, or type 0 for menu.",  # needs native review
    },
    "prompt.expected_message": {
        "fr": "J'attends le texte du message. Collez-le, ou tapez 0 pour le menu.",
        "en": "I'm waiting for the message text. Paste it, or type 0 for the menu.",
        "pcm": "I dey wait for di message text. Paste am, or type 0 for menu.",  # needs native review
    },
    "image.choice": {
        "fr": "Que représente cette image ?\n1. Photo d'un produit\n2. Preuve d'arnaque",
        "en": "What is this image?\n1. Product photo\n2. Scam evidence",
        "pcm": "Wetin be dis image?\n1. Photo of product\n2. Proof of scam",  # needs native review
    },
    "help.main": {
        "fr": (
            "Tchek-Am vous aide à vérifier un numéro, une photo ou un message avant de payer.\n"
            "Envoyez simplement un numéro, une photo ou un message.\n"
            "0 = menu, LANG = langue, STOP GROUPE = ne plus être pris en compte dans les groupes partenaires."
        ),
        "en": (
            "Tchek-Am helps you check a number, a photo or a message before you pay.\n"
            "Just send a number, a photo or a message.\n"
            "0 = menu, LANG = language, STOP GROUP = stop being included in partner groups."
        ),
        "pcm": (
            "Tchek-Am dey help you check number, photo or message before you pay.\n"
            "Just send number, photo or message.\n"
            "0 = menu, LANG = language, STOP GROUP = make una no put me for partner groups again."
        ),  # needs native review
    },
    "common.coming_soon": {
        "fr": "Cette fonction arrive bientôt. Tapez 0 pour le menu.",
        "en": "This feature is coming soon. Type 0 for the menu.",
        "pcm": "Dis thing de come soon. Type 0 for menu.",  # needs native review
    },
    "common.unsupported": {
        "fr": "Je ne peux pas lire ce type de message. Tapez 0 pour le menu.",
        "en": "I can't read this kind of message. Type 0 for the menu.",
        "pcm": "I no fit read dis kind message. Type 0 for menu.",  # needs native review
    },
    "check.number.header": {
        "fr": "📞 {number} ({operator})",
        "en": "📞 {number} ({operator})",
        "pcm": "📞 {number} ({operator})",  # needs native review
    },
    "check.number.header_no_operator": {
        "fr": "📞 {number}",
        "en": "📞 {number}",
        "pcm": "📞 {number}",  # needs native review
    },
    "check.number.green": {
        "fr": "🟢 Aucun signalement pour ce numéro.\nCela ne prouve pas que le vendeur est honnête.",
        "en": "🟢 No reports for this number.\nThat doesn't prove the seller is honest.",
        "pcm": "🟢 No report dey for dis number.\nDat no mean say di seller dey honest.",  # needs native review
    },
    "check.number.yellow_one": {
        "fr": "🟡 1 signalement en attente de vérification.",
        "en": "🟡 1 report waiting for review.",
        "pcm": "🟡 1 report dey wait for review.",  # needs native review
    },
    "check.number.yellow": {
        "fr": "🟡 {n} signalements en attente de vérification.",
        "en": "🟡 {n} reports waiting for review.",
        "pcm": "🟡 {n} reports dey wait for review.",  # needs native review
    },
    "check.number.orange_one": {
        "fr": "🟠 Signalé par 1 personne, preuves examinées. Pas assez pour un avertissement de risque élevé. Soyez prudent.",
        "en": "🟠 Reported by 1 person, evidence reviewed. Not enough for a high-risk warning. Be careful.",
        "pcm": "🟠 1 person report am, we don check di evidence. E no reach high-risk warning. Be careful.",  # needs native review
    },
    "check.number.orange": {
        "fr": "🟠 Signalé par {k} personnes, preuves examinées. Pas assez pour un avertissement de risque élevé. Soyez prudent.",
        "en": "🟠 Reported by {k} people, evidence reviewed. Not enough for a high-risk warning. Be careful.",
        "pcm": "🟠 {k} people report am, we don check di evidence. E no reach high-risk warning. Be careful.",  # needs native review
    },
    "check.number.orange_reviewed": {
        "fr": "🟠 Des signalements examinés existent. Pas assez pour un avertissement de risque élevé. Soyez prudent.",
        "en": "🟠 Reviewed reports exist. Not enough for a high-risk warning. Be careful.",
        "pcm": "🟠 Reviewed reports dey. E no reach high-risk warning. Be careful.",  # needs native review
    },
    "check.number.red": {
        "fr": "🔴 Risque élevé : signalé par {k} personnes différentes. Preuves examinées.",
        "en": "🔴 High risk: reported by {k} different people. Evidence reviewed.",
        "pcm": "🔴 High risk: {k} different people report am. We don check di evidence.",  # needs native review
    },
    "check.number.red_proof": {
        "fr": "🔴 Risque élevé : 1 signalement examiné avec preuve de paiement.",
        "en": "🔴 High risk: 1 reviewed report with payment proof.",
        "pcm": "🔴 High risk: 1 reviewed report wey get payment proof.",  # needs native review
    },
    "check.number.last_report": {
        "fr": "Dernier signalement : {when}",
        "en": "Last report: {when}",
        "pcm": "Last report: {when}",  # needs native review
    },
    "check.number.under_appeal": {
        "fr": "⚖️ En cours de contestation : le titulaire de ce numéro conteste les signalements.",
        "en": "⚖️ Under appeal: the owner of this number is contesting the reports.",
        "pcm": "⚖️ Appeal dey: di owner of dis number dey contest di reports.",  # needs native review
    },
    "check.number.names": {
        "fr": "Noms vus sur des paiements : {names}",
        "en": "Names seen on payments: {names}",
        "pcm": "Names wey show for payments: {names}",  # needs native review
    },
    "check.number.checked_times": {
        "fr": "Vérifié {n} fois ce mois-ci.",
        "en": "Checked {n} times this month.",
        "pcm": "Dem don check am {n} times dis month.",  # needs native review
    },
    "check.number.tips": {
        "fr": "Conseils : préférez le paiement à la livraison, rencontrez-vous dans un lieu public, et vérifiez que le nom affiché sur MoMo/OM correspond au vendeur.",
        "en": "Tips: prefer cash on delivery, meet in a public place, and check that the name shown on MoMo/OM matches the seller.",
        "pcm": "Tips: better pay when dem deliver, meet for public place, and check say di name wey show for MoMo/OM na di seller own.",  # needs native review
    },
    "check.number.footer": {
        "fr": "Pour signaler ce numéro : répondez 4. Si c'est votre numéro et que vous n'êtes pas d'accord : répondez CONTESTER.",
        "en": "To report this number: reply 4. If this is your number and you disagree: reply APPEAL.",
        "pcm": "To report dis number: reply 4. If na your number and you no agree: reply APPEAL.",  # needs native review
    },
    "check.number.too_many": {
        "fr": "Vous avez envoyé plus de 3 numéros : j'ai vérifié les 3 premiers.",
        "en": "You sent more than 3 numbers: I checked the first 3.",
        "pcm": "You send more than 3 numbers: I check di first 3.",  # needs native review
    },
    "check.limit_reached": {
        "fr": "Vous avez atteint la limite de vérifications pour aujourd'hui. Revenez demain, merci de votre patience.",
        "en": "You've reached today's limit of checks. Please come back tomorrow, and thank you for your patience.",
        "pcm": "You don reach di limit of checks for today. Abeg come back tomorrow, tank you for patience.",  # needs native review
    },
    "error.generic": {
        "fr": "Désolé, un problème est survenu. Réessayez dans un instant.",
        "en": "Sorry, something went wrong. Please try again in a moment.",
        "pcm": "Sorry, wahala happen. Try again small time.",  # needs native review
    },
}

DEFAULT_LANG = "fr"


def t(key: str, lang: str | None, **fmt: object) -> str:
    """Look up copy for `key`, falling back to French. Unknown keys and missing fmt args raise."""
    entry = CATALOG[key]
    text = entry.get(lang or DEFAULT_LANG) or entry[DEFAULT_LANG]
    # str.format raises KeyError on a missing argument; that is deliberate, never swallow it.
    return text.format(**fmt)
