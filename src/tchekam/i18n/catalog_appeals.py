"""Copy for appeals (F6), merged into CATALOG by catalog.py.

Neutral wording: describes reports and outcomes, never labels anyone.
"""

APPEAL_COPY: dict[str, dict[str, str]] = {
    "appeal.cm_only": {
        "fr": "Vous ne pouvez contester que le numéro camerounais depuis lequel vous nous écrivez.",
        "en": "You can only contest the Cameroonian number you are writing from.",
        "pcm": "You fit only contest di Cameroon number wey you dey write us from.",  # needs native review
    },
    "appeal.own_number_only": {
        "fr": "Vous ne pouvez contester que le numéro depuis lequel vous nous écrivez, pas un autre numéro.",
        "en": "You can only contest the number you are writing from, not another number.",
        "pcm": "You fit only contest di number wey you dey write us from, no be another number.",  # needs native review
    },
    "appeal.nothing": {
        "fr": "Il n'y a aucun signalement à contester pour votre numéro.",
        "en": "There are no reports to contest for your number.",
        "pcm": "Nothing dey to contest for your number.",  # needs native review
    },
    "appeal.already_open": {
        "fr": "Vous avez déjà une contestation en cours d'examen. Nous vous écrirons dès qu'elle sera traitée.",
        "en": "You already have an appeal being reviewed. We will write to you as soon as it is decided.",
        "pcm": "You don already get one appeal wey dem dey check. We go write you when dem decide am.",  # needs native review
    },
    "appeal.number_busy": {
        "fr": "Une contestation est déjà en cours d'examen pour ce numéro. Réessayez une fois qu'elle sera traitée.",
        "en": "An appeal is already being reviewed for this number. Try again once it is decided.",
        "pcm": "Dem dey already check one appeal for dis number. Try again when dem don decide am.",  # needs native review
    },
    "appeal.limit_reached": {
        "fr": "Vous avez atteint la limite de contestations pour aujourd'hui. Réessayez demain.",
        "en": "You have reached today's limit for appeals. Please try again tomorrow.",
        "pcm": "You don reach di limit of appeals for today. Try again tomorrow.",  # needs native review
    },
    "appeal.choose_kind": {
        "fr": "Que souhaitez-vous contester ?\n1. Ces signalements sont erronés\n2. Ce numéro est nouveau pour moi\nCANCEL = annuler",
        "en": "What would you like to contest?\n1. These reports are wrong\n2. This number is new to me\nCANCEL = cancel",
        "pcm": "Wetin you want contest?\n1. Dis reports no correct\n2. Dis number na new for me\nCANCEL = cancel",  # needs native review
    },
    "appeal.ask_month": {
        "fr": "Depuis quand avez-vous ce numéro ? Indiquez le mois et l'année, par exemple 06/2026 ou juin 2026.",
        "en": "Since when have you had this number? Give the month and year, for example 06/2026 or June 2026.",
        "pcm": "Since when you get dis number? Tell me di month and year, like 06/2026 or June 2026.",  # needs native review
    },
    "appeal.month_invalid": {
        "fr": "Je n'ai pas compris cette date. Écrivez le mois et l'année (06/2026 ou juin 2026), sans date dans le futur.",
        "en": "I did not understand that date. Write the month and year (06/2026 or June 2026), not in the future.",
        "pcm": "I no understand dat date. Write di month and year (06/2026 or June 2026), no future date.",  # needs native review
    },
    "appeal.ask_statement": {
        "fr": "Expliquez en un message pourquoi vous contestez (maximum {n} caractères).",
        "en": "Explain in one message why you are contesting (maximum {n} characters).",
        "pcm": "Explain for one message why you dey contest (maximum {n} characters).",  # needs native review
    },
    "appeal.statement_too_long": {
        "fr": "Ce message est trop long. Résumez-le en {n} caractères maximum.",
        "en": "That message is too long. Please shorten it to {n} characters at most.",
        "pcm": "Dat message too long. Make am short, {n} characters at most.",  # needs native review
    },
    "appeal.ask_evidence": {
        "fr": "Vous pouvez envoyer des images ou des messages vocaux pour appuyer votre demande. Envoyez FINI quand vous avez terminé (même sans pièce jointe), ou CANCEL pour annuler.",
        "en": "You can send images or voice notes to support your request. Send DONE when you are finished (even with no attachment), or CANCEL to stop.",
        "pcm": "You fit send images or voice notes to support your request. Send DONE when you finish (even if nothing), or CANCEL to stop.",  # needs native review
    },
    "appeal.file_noted": {
        "fr": "Reçu. Envoyez d'autres pièces, ou FINI pour terminer.",
        "en": "Received. Send more, or DONE to finish.",
        "pcm": "Dem don receive am. Send more, or DONE to finish.",  # needs native review
    },
    "appeal.file_failed": {
        "fr": "Je n'ai pas pu récupérer ce fichier. Renvoyez-le, ou envoyez FINI pour continuer sans lui.",
        "en": "I could not get that file. Send it again, or send DONE to continue without it.",
        "pcm": "I no fit get dat file. Send am again, or send DONE to continue without am.",  # needs native review
    },
    "appeal.limit_items": {
        "fr": "Vous avez atteint le nombre maximum de pièces jointes. Envoyez FINI pour terminer.",
        "en": "You have reached the maximum number of attachments. Send DONE to finish.",
        "pcm": "You don reach di maximum attachments. Send DONE to finish.",  # needs native review
    },
    "appeal.limit_size": {
        "fr": "Ce fichier est trop volumineux. Envoyez-en un plus léger, ou FINI pour continuer.",
        "en": "That file is too large. Send a smaller one, or DONE to continue.",
        "pcm": "Dat file too big. Send smaller one, or DONE to continue.",  # needs native review
    },
    "appeal.still_processing": {
        "fr": "Je termine de récupérer vos fichiers. Renvoyez FINI dans un instant.",
        "en": "I am still processing your files. Send DONE again in a moment.",
        "pcm": "I dey still process your files. Send DONE again small time.",  # needs native review
    },
    "appeal.submitted": {
        "fr": "Merci. Votre contestation est enregistrée. Un modérateur va l'examiner et nous vous écrirons pour vous donner la décision. En attendant, la vérification de votre numéro indique « en cours de contestation ».",
        "en": 'Thank you. Your appeal is registered. A moderator will review it and we will write to you with the decision. Meanwhile, checks on your number will say "under appeal".',
        "pcm": 'Thank you. Your appeal don register. Moderator go review am and we go write you di decision. For now, di check for your number go talk say "appeal dey".',  # needs native review
    },
    "appeal.cancelled": {
        "fr": "C'est annulé. Rien n'a été enregistré.",
        "en": "Cancelled. Nothing was saved.",
        "pcm": "Dem don cancel am. Nothing save.",  # needs native review
    },
    "appeal.lost": {
        "fr": "Cette demande n'existe plus. Répondez CONTESTER pour recommencer.",
        "en": "That request no longer exists. Reply APPEAL to start again.",
        "pcm": "Dat request no dey again. Reply APPEAL to start again.",  # needs native review
    },
    "notify.rejected.after_review": {
        "fr": "Après un nouvel examen, votre signalement ({reference}) n'est plus pris en compte. Merci d'avoir pris le temps de nous écrire.",
        "en": "After a new review, your report ({reference}) no longer counts. Thank you for taking the time to write to us.",
        "pcm": "After dem review am again, your report ({reference}) no count again. Thank you say you take time write us.",  # needs native review
    },
    "appeal.notify.approved": {
        "fr": "Bonne nouvelle : votre contestation a été acceptée. Les signalements concernés ne comptent plus pour votre numéro.",
        "en": "Good news: your appeal was accepted. The reports concerned no longer count for your number.",
        "pcm": "Good news: dem accept your appeal. Di reports no count again for your number.",  # needs native review
    },
    "appeal.notify.rejected": {
        "fr": "Après examen, votre contestation n'a pas pu être acceptée. Si vous avez d'autres éléments, répondez CONTESTER pour en déposer une nouvelle.",
        "en": "After review, your appeal could not be accepted. If you have more information, reply APPEAL to submit a new one.",
        "pcm": "After dem review am, dem no fit accept your appeal. If you get more information, reply APPEAL to send new one.",  # needs native review
    },
    "appeal.notify.more_help": {
        "fr": "Besoin d'aide ? Contactez-nous : {url}",
        "en": "Need help? Contact us: {url}",
        "pcm": "You need help? Contact us: {url}",  # needs native review
    },
}
