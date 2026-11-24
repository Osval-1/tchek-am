"""Agent status copy. PCM requires native review before its cohort is enabled."""

STATUS_COPY = {
    "none": (
        "Aucun signalement à afficher.",
        "No reports to show.",
        "No report for show.",
    ),  # needs native review
    "draft": (
        "Brouillon : pas encore envoyé.",
        "Draft: not submitted yet.",
        "Draft: you never send am yet.",  # needs native review
    ),
    "pending": (
        "En attente de relecture.",
        "Waiting for review.",
        "E dey wait for review.",
    ),  # needs native review
    "needs_info": (
        "Un complément est demandé.",
        "More information requested.",
        "Dem need more information.",  # needs native review
    ),
    "approved": (
        "Signalement accepté après relecture.",
        "Report accepted after review.",
        "Dem don review and accept report.",  # needs native review
    ),
    "rejected": (
        "Signalement non retenu.",
        "Report not accepted.",
        "Dem no accept report.",
    ),  # needs native review
    "merged": (
        "Signalement regroupé avec un autre.",
        "Report merged with another.",
        "Dem join report with another one.",  # needs native review
    ),
    "withdrawn": (
        "Signalement retiré.",
        "Report withdrawn.",
        "Report don withdraw.",
    ),  # needs native review
}

AGENT_COPY = {
    f"agent.status.{code}": dict(zip(("fr", "en", "pcm"), texts, strict=True))
    for code, texts in STATUS_COPY.items()
}

AGENT_COPY.update(
    {
        "agent.image.purpose": {
            "fr": "Que souhaitez-vous vérifier dans cette image ? Envoyez une courte question avec l’image. Pour un signalement, tapez 4.",
            "en": "What would you like to check in this image? Send a short question with the image. To start a report, type 4.",
            "pcm": "Wetin you wan check for dis image? Send short question with di image. If you wan report, type 4.",  # needs native review
        },
        "agent.image.confirm": {
            "fr": "J’ai lu : {values}. Vérifiez ces valeurs dans l’original, puis retapez-les pour continuer. Aucune valeur n’a été envoyée comme signalement.",
            "en": "I read: {values}. Check these values against the original, then type them to continue. No values have been submitted as a report.",
            "pcm": "I read: {values}. Check dem for di original, then type dem make we continue. We never submit any value as report.",  # needs native review
        },
        "agent.name.found": {
            "fr": "Le nom masqué {name} apparaît dans des signalements relus. Un nom ne suffit pas à identifier une personne. Vérifiez aussi le numéro ; tapez 6 pour contester votre propre numéro.",
            "en": "The masked name {name} appears in reviewed reports. A name alone does not identify a person. Check the phone number too; type 6 to contest your own number.",
            "pcm": "Di masked name {name} dey for reports wey dem don review. Name alone no fit identify person. Check di phone number too; type 6 if you wan contest your own number.",  # needs native review
        },
        "agent.name.none": {
            "fr": "Aucun résultat relu pour le nom masqué {name}. Cela ne garantit pas une transaction. Vérifiez aussi le numéro et le nom du destinataire avant tout paiement.",
            "en": "No reviewed match for the masked name {name}. This does not guarantee a transaction. Also check the phone number and recipient name before paying.",
            "pcm": "No reviewed match for di masked name {name}. Dis no guarantee transaction. Check di phone number and receiver name before you pay.",  # needs native review
        },
    }
)
