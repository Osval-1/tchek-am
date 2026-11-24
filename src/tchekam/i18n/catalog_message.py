"""Copy for the message check (F3), merged into CATALOG by catalog.py.

Kept in its own file so the feature adds copy without touching the shared catalogue body.
Wording describes the message, never the sender, and never says a message is safe or not.
"""

MESSAGE_CHECK_COPY: dict[str, dict[str, str]] = {
    "check.message.checking": {
        "fr": "J'analyse votre message, un instant…",
        "en": "Checking your message, one moment…",
        "pcm": "I dey check your message, wait small…",  # needs native review
    },
    "check.message.flags_header": {
        "fr": "⚠ Signaux d'alerte repérés dans ce message :",
        "en": "⚠ Red flags spotted in this message:",
        "pcm": "⚠ Red flags dey inside dis message:",  # needs native review
    },
    "check.message.none": {
        "fr": "Je n'ai repéré aucun des signaux d'alerte courants dans ce message.",
        "en": "I did not spot any of the common red flags in this message.",
        "pcm": "I no see any of di common red flags for dis message.",  # needs native review
    },
    "check.message.flag.upfront_payment": {
        "fr": "On demande de payer en entier ou d'avance, avant la livraison.",
        "en": "It asks for full or advance payment before delivery.",
        "pcm": "Dem dey ask make you pay full or before dem deliver.",  # needs native review
    },
    "check.message.flag.urgency": {
        "fr": "Le message presse d'agir tout de suite (« aujourd'hui seulement », « dernier article »).",
        "en": 'It pushes you to act right now ("only today", "last one").',
        "pcm": 'Dem dey rush you make you do am now now ("only today", "last one").',  # needs native review
    },
    "check.message.flag.delivery_intermediary": {
        "fr": "La livraison passe par un intermédiaire (transporteur, livreur, représentant).",
        "en": "Delivery goes through a go-between (transporter, delivery person, representative).",
        "pcm": "Delivery dey pass through another person (transporter, delivery man, representative).",  # needs native review
    },
    "check.message.flag.payee_mismatch": {
        "fr": "Le paiement serait à envoyer à un nom différent de celui du vendeur.",
        "en": "Payment would go to a name different from the seller's.",
        "pcm": "Di payment go go for name wey no be di seller own.",  # needs native review
    },
    "check.message.flag.refuses_cod_or_meeting": {
        "fr": "Le paiement à la livraison ou une rencontre en personne est refusé.",
        "en": "Cash on delivery or meeting in person is refused.",
        "pcm": "Dem no gree pay when dem deliver or make una meet.",  # needs native review
    },
    "check.message.flag.price_too_low": {
        "fr": "Le prix annoncé est très inférieur au prix habituel de cet article.",
        "en": "The price quoted is far below the usual price for this item.",
        "pcm": "Di price wey dem talk low well well pass di normal price for dis thing.",  # needs native review
    },
    "check.message.numbers_header": {
        "fr": "Numéros trouvés dans le message :",
        "en": "Numbers found in the message:",
        "pcm": "Numbers wey dey inside di message:",  # needs native review
    },
    "check.message.contest": {
        "fr": "Si c'est votre numéro et que vous n'êtes pas d'accord : répondez CONTESTER.",
        "en": "If this is your number and you disagree: reply APPEAL.",
        "pcm": "If na your number and you no agree: reply APPEAL.",  # needs native review
    },
    "check.message.number_unavailable": {
        "fr": "Vérification indisponible pour le moment. Envoyez-moi ce numéro seul pour réessayer.",
        "en": "Check unavailable right now. Send me this number alone to try again.",
        "pcm": "Check no dey work now. Send me dis number alone make you try again.",  # needs native review
    },
    "check.message.caution": {
        "fr": "Les signaux d'alerte ne prouvent rien. Préférez le paiement à la livraison.",
        "en": "Red flags don't prove anything. Prefer cash on delivery.",
        "pcm": "Red flags no be proof. Better pay when dem deliver.",  # needs native review
    },
    "check.message.failed": {
        "fr": "Je n'ai pas pu analyser ce message. Renvoyez-le, ou tapez 0 pour le menu.",
        "en": "I could not check this message. Please send it again, or type 0 for the menu.",
        "pcm": "I no fit check dis message. Abeg send am again, or type 0 for menu.",  # needs native review
    },
}
