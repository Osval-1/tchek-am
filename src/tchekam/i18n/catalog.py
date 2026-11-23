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
    "report.instructions": {
        "fr": (
            "Signaler une arnaque : envoyez-moi vos preuves, une par message.\n"
            "• captures d'écran de la discussion avec le vendeur\n"
            "• capture du SMS MoMo / Orange Money du paiement\n"
            "• capture de l'annonce du produit\n"
            "• une note vocale ou un texte qui raconte ce qui s'est passé\n"
            "Quand vous avez terminé, répondez FINI (ou 1). ANNULER pour arrêter."
        ),
        "en": (
            "Report a scam: send me your evidence, one item per message.\n"
            "• screenshots of the chat with the seller\n"
            "• a screenshot of the MoMo / Orange Money payment SMS\n"
            "• a screenshot of the product post\n"
            "• a voice note or a text telling what happened\n"
            "When you have finished, reply DONE (or 1). CANCEL to stop."
        ),
        "pcm": (
            "Report scam: send me your evidence, one by one.\n"
            "• screenshot of di chat with di seller\n"
            "• screenshot of di MoMo / Orange Money SMS for di payment\n"
            "• screenshot of di product post\n"
            "• voice note or text wey talk wetin happen\n"
            "When you finish, reply DONE (or 1). CANCEL to stop."
        ),  # needs native review
    },
    "report.count.image_one": {
        "fr": "1 image",
        "en": "1 image",
        "pcm": "1 image",  # needs native review
    },
    "report.count.image": {
        "fr": "{n} images",
        "en": "{n} images",
        "pcm": "{n} images",  # needs native review
    },
    "report.count.voice_one": {
        "fr": "1 note vocale",
        "en": "1 voice note",
        "pcm": "1 voice note",  # needs native review
    },
    "report.count.voice": {
        "fr": "{n} notes vocales",
        "en": "{n} voice notes",
        "pcm": "{n} voice notes",  # needs native review
    },
    "report.count.none": {
        "fr": "aucun fichier",
        "en": "no files",
        "pcm": "no file",  # needs native review
    },
    "report.ack": {
        "fr": "✅ Reçu : {items}. Envoyez la suite, ou FINI quand vous avez terminé.",
        "en": "✅ Received: {items}. Send more, or DONE when you have finished.",
        "pcm": "✅ I don receive: {items}. Send more, or DONE when you finish.",  # needs native review
    },
    "report.story_noted": {
        "fr": "📝 Noté. Envoyez la suite, ou FINI quand vous avez terminé.",
        "en": "📝 Noted. Send more, or DONE when you have finished.",
        "pcm": "📝 I don note am. Send more, or DONE when you finish.",  # needs native review
    },
    "report.story_full": {
        "fr": "Votre récit est déjà long, merci. Envoyez des captures d'écran, ou FINI pour continuer.",
        "en": "Your account of events is already long, thank you. Send screenshots, or DONE to continue.",
        "pcm": "Your story don long well, tank you. Send screenshot, or DONE to continue.",  # needs native review
    },
    "report.limit_items": {
        "fr": "Merci, vous avez déjà envoyé 10 fichiers, c'est le maximum. Répondez FINI pour continuer.",
        "en": "Thank you, you have already sent 10 files, which is the maximum. Reply DONE to continue.",
        "pcm": "Tank you, you don send 10 files, na di maximum. Reply DONE to continue.",  # needs native review
    },
    "report.limit_size": {
        "fr": "Désolé, ce fichier dépasse la taille totale autorisée (15 Mo). Il n'a pas été ajouté. Répondez FINI pour continuer.",
        "en": "Sorry, this file goes over the total size allowed (15 MB). It was not added. Reply DONE to continue.",
        "pcm": "Sorry, dis file pass di total size wey we allow (15 MB). I no add am. Reply DONE to continue.",  # needs native review
    },
    "report.file_failed": {
        "fr": "Désolé, je n'ai pas pu lire ce fichier. Merci de le renvoyer.",
        "en": "Sorry, I could not read that file. Please send it again.",
        "pcm": "Sorry, I no fit read dat file. Abeg send am again.",  # needs native review
    },
    "report.unsupported_item": {
        "fr": "Je ne peux pas utiliser ce type de fichier. Envoyez des images, des notes vocales ou du texte.",
        "en": "I can't use this kind of file. Send images, voice notes or text.",
        "pcm": "I no fit use dis kind file. Send images, voice notes or text.",  # needs native review
    },
    "report.need_one_item": {
        "fr": "Envoyez au moins une capture d'écran, une note vocale ou un texte avant de répondre FINI.",
        "en": "Send at least one screenshot, voice note or text before replying DONE.",
        "pcm": "Send at least one screenshot, voice note or text before you reply DONE.",  # needs native review
    },
    "report.still_processing": {
        "fr": "Je traite encore vos fichiers. Renvoyez FINI dans un instant.",
        "en": "I'm still processing your files. Send DONE again in a moment.",
        "pcm": "I still dey work on your files. Send DONE again small time.",  # needs native review
    },
    "report.analysing": {
        "fr": "🔎 J'analyse vos preuves, cela peut prendre une minute…",
        "en": "🔎 Analysing your evidence, this can take a minute…",
        "pcm": "🔎 I dey check your evidence, e fit take one minute…",  # needs native review
    },
    "report.analysis_wait": {
        "fr": "J'analyse encore vos preuves. Merci de patienter un instant.",
        "en": "I'm still analysing your evidence. Please wait a moment.",
        "pcm": "I still dey check your evidence. Abeg wait small.",  # needs native review
    },
    "report.analysis_failed": {
        "fr": "Désolé, l'analyse n'a pas abouti. Répondez FINI pour réessayer.",
        "en": "Sorry, the analysis did not finish. Reply DONE to try again.",
        "pcm": "Sorry, di check no finish. Reply DONE to try again.",  # needs native review
    },
    "report.cancelled": {
        "fr": "Votre signalement est annulé. Tapez 0 pour le menu.",
        "en": "Your report has been cancelled. Type 0 for the menu.",
        "pcm": "Your report don cancel. Type 0 for menu.",  # needs native review
    },
    "report.ask_details": {
        "fr": "Je n'ai pas bien compris certains détails. Tapez le numéro du vendeur et le montant payé (exemple : 677123456 25000).",
        "en": "I couldn't make out some details. Type the seller's number and the amount paid (example: 677123456 25000).",
        "pcm": "I no understand some details well. Type di seller number and di money wey you pay (example: 677123456 25000).",  # needs native review
    },
    "report.ask_details_again": {
        "fr": "Je ne trouve pas de numéro camerounais valide. Tapez le numéro du vendeur (exemple : 677123456 25000).",
        "en": "I can't find a valid Cameroonian number. Type the seller's number (example: 677123456 25000).",
        "pcm": "I no see correct Cameroon number. Type di seller number (example: 677123456 25000).",  # needs native review
    },
    "report.resume_choice": {
        "fr": "Vous avez un signalement commencé ({items}).\n1. Continuer ce signalement\n2. En commencer un nouveau",
        "en": "You have a report in progress ({items}).\n1. Continue that report\n2. Start a new one",
        "pcm": "You get one report wey you don start ({items}).\n1. Continue dat report\n2. Start new one",  # needs native review
    },
    "report.resumed": {
        "fr": "D'accord, on continue ({items}). Envoyez la suite, ou FINI quand vous avez terminé.",
        "en": "OK, let's continue ({items}). Send more, or DONE when you have finished.",
        "pcm": "OK, make we continue ({items}). Send more, or DONE when you finish.",  # needs native review
    },
    "report.summary_neutral": {
        "fr": "Signalement d'un problème avec un vendeur, avec les preuves jointes.",
        "en": "Report of a problem with a seller, with the attached evidence.",
        "pcm": "Report of one wahala with one seller, with di evidence wey dey attached.",  # needs native review
    },
    "report.files_lost_one": {
        "fr": "Désolé, 1 fichier n'a pas pu être lu. Merci de le renvoyer, puis répondez FINI.",
        "en": "Sorry, 1 file could not be read. Please resend it, then reply DONE.",
        "pcm": "Sorry, I no fit read 1 file. Abeg send am again, then reply DONE.",  # needs native review
    },
    "report.files_lost": {
        "fr": "Désolé, {n} fichiers n'ont pas pu être lus. Merci de les renvoyer, puis répondez FINI.",
        "en": "Sorry, {n} files could not be read. Please resend them, then reply DONE.",
        "pcm": "Sorry, I no fit read {n} files. Abeg send dem again, then reply DONE.",  # needs native review
    },
    "report.confirm.list": {
        "fr": (
            "📋 Voici ce que j'ai compris. Vérifiez :\n"
            "1. Numéro(s) du vendeur : {sellers}\n"
            "2. Nom(s) MoMo / Orange Money : {payees}\n"
            "3. Montant : {amount}\n"
            "4. Date : {date}\n"
            "5. Résumé : {summary}\n"
            "Fichiers reçus : {items}\n\n"
            "Répondez OK pour confirmer, ou « numéro nouvelle valeur » pour corriger "
            "(exemple : 1 677123456). ANNULER pour annuler, 0 pour le menu (le brouillon est gardé)."
        ),
        "en": (
            "📋 Here is what I understood. Please check:\n"
            "1. Seller number(s): {sellers}\n"
            "2. MoMo / Orange Money name(s): {payees}\n"
            "3. Amount: {amount}\n"
            "4. Date: {date}\n"
            "5. Summary: {summary}\n"
            "Files received: {items}\n\n"
            'Reply OK to confirm, or "number new value" to change a line '
            "(example: 1 677123456). CANCEL to cancel, 0 for the menu (your draft is kept)."
        ),
        "pcm": (
            "📋 Na wetin I understand be dis. Abeg check am:\n"
            "1. Seller number(s): {sellers}\n"
            "2. MoMo / Orange Money name(s): {payees}\n"
            "3. Money: {amount}\n"
            "4. Date: {date}\n"
            "5. Summary: {summary}\n"
            "Files wey I receive: {items}\n\n"
            'Reply OK to confirm, or "number new value" to change one line '
            "(example: 1 677123456). CANCEL to stop, 0 for menu (I go keep your draft)."
        ),  # needs native review
    },
    "report.confirm.help": {
        "fr": "Je n'ai pas compris. Répondez OK, ou « numéro nouvelle valeur » avec un numéro de 1 à 5 (exemple : 3 25000). Un tiret efface les champs 2 à 4 (exemple : 4 -).",
        "en": 'I did not understand. Reply OK, or "number new value" with a number from 1 to 5 (example: 3 25000). A dash clears fields 2 to 4 (example: 4 -).',
        "pcm": 'I no understand. Reply OK, or "number new value" with number from 1 to 5 (example: 3 25000). Dash go clear fields 2 to 4 (example: 4 -).',  # needs native review
    },
    "report.confirm.bad_number": {
        "fr": "Je ne trouve pas de numéro camerounais valide. Exemple : 1 677123456 (jusqu'à 3 numéros).",
        "en": "I can't find a valid Cameroonian number. Example: 1 677123456 (up to 3 numbers).",
        "pcm": "I no see correct Cameroon number. Example: 1 677123456 (up to 3 numbers).",  # needs native review
    },
    "report.confirm.bad_name": {
        "fr": "Je n'ai pas pu lire ce nom (60 caractères maximum chacun). Exemple : 2 Jean Dupont, Marie Ngo. Tapez 2 - pour effacer.",
        "en": "I could not read that name (60 characters at most each). Example: 2 Jean Dupont, Marie Ngo. Type 2 - to clear it.",
        "pcm": "I no fit read dat name (60 letters at most for each). Example: 2 Jean Dupont, Marie Ngo. Type 2 - to clear am.",  # needs native review
    },
    "report.confirm.bad_amount": {
        "fr": "Montant non valide. Exemple : 3 25000 (en FCFA, au maximum 100 000 000). Tapez 3 - pour effacer.",
        "en": "That amount is not valid. Example: 3 25000 (in FCFA, 100,000,000 at most). Type 3 - to clear it.",
        "pcm": "Dat amount no correct. Example: 3 25000 (for FCFA, 100,000,000 at most). Type 3 - to clear am.",  # needs native review
    },
    "report.confirm.bad_date": {
        "fr": "Date non valide (pas dans le futur, pas plus de 5 ans). Exemples : 4 20/11/2026 ou 4 12 mars 2026. Tapez 4 - pour effacer.",
        "en": "That date is not valid (not in the future, not older than 5 years). Examples: 4 20/11/2026 or 4 12 March 2026. Type 4 - to clear it.",
        "pcm": "Dat date no correct (no future date, no pass 5 years). Examples: 4 20/11/2026 or 4 12 March 2026. Type 4 - to clear am.",  # needs native review
    },
    "report.confirm.bad_summary": {
        "fr": "Le résumé doit faire entre 1 et 500 caractères. Exemple : 5 J'ai payé le téléphone mais il n'a jamais été livré.",
        "en": "The summary must be between 1 and 500 characters. Example: 5 I paid for the phone but it was never delivered.",
        "pcm": "Di summary must be 1 to 500 letters. Example: 5 I pay for di phone but dem never deliver am.",  # needs native review
    },
    "report.confirm.need_seller": {
        "fr": "Il me faut au moins un numéro de vendeur valide pour envoyer le signalement. Tapez le numéro après « 1 » (exemple : 1 677123456).",
        "en": 'I need at least one valid seller number to send the report. Type the number after "1" (example: 1 677123456).',
        "pcm": 'I need at least one correct seller number to send di report. Type di number after "1" (example: 1 677123456).',  # needs native review
    },
    # legal review: wording must be checked by the lawyer
    "report.false_warning": {
        "fr": "Attention : un signalement sciemment faux peut constituer une infraction et donner lieu à des poursuites.",
        "en": "Warning: knowingly false reports can be an offence and lead to legal action.",
        "pcm": "Warning: if person knowingly send false report, e fit be offence and e fit lead to legal action.",  # needs native review
    },
    "report.consent.terms": {
        "fr": (
            "Avant d'envoyer, merci de confirmer :\n"
            "• ce que je déclare est vrai, à ma connaissance ;\n"
            "• mes preuves sont examinées par le modérateur de Tchek-Am et traitées par des "
            "prestataires techniques (analyse par IA et transcription des notes vocales) qui "
            "agissent pour le compte de Tchek-Am ;\n"
            "• elles ne sont jamais montrées aux acheteurs et mon identité n'est jamais rendue "
            "publique.\n\n"
            "{warning}\n\n"
            "Conditions complètes : {url}\n\n"
            "1 = j'accepte, 2 = j'annule"
        ),
        "en": (
            "Before sending, please confirm:\n"
            "• what I say is true to the best of my knowledge;\n"
            "• my evidence is reviewed by the Tchek-Am moderator and processed by technical "
            "service providers (AI analysis and voice-note transcription) that handle it on "
            "Tchek-Am's behalf;\n"
            "• it is never shown to buyers and my identity is never made public.\n\n"
            "{warning}\n\n"
            "Full terms: {url}\n\n"
            "1 = I agree, 2 = cancel"
        ),
        "pcm": (
            "Before I send am, abeg confirm:\n"
            "• wetin I talk na true as far as I know;\n"
            "• Tchek-Am moderator go check my evidence, and technical service providers "
            "(AI analysis and voice-note transcription) go handle am for Tchek-Am;\n"
            "• dem no go ever show am to buyers, and dem no go ever show my identity to people.\n\n"
            "{warning}\n\n"
            "Full terms: {url}\n\n"
            "1 = I agree, 2 = cancel"
        ),  # needs native review
    },
    "report.consent.declined": {
        "fr": "Pas de problème, rien n'est envoyé et votre signalement est annulé. Merci de votre temps. Tapez 0 pour le menu.",
        "en": "No problem, nothing is sent and your report is cancelled. Thank you for your time. Type 0 for the menu.",
        "pcm": "No wahala, we no send anything and your report don cancel. Thank you for your time. Type 0 for menu.",  # needs native review
    },
    "report.optin.ask": {
        "fr": "Pouvons-nous utiliser vos notes vocales et vos corrections pour améliorer la reconnaissance vocale ? C'est indépendant de votre signalement.\n1 = oui, 2 = non",
        "en": "May we use your voice notes and your corrections to improve speech recognition? This is separate from your report.\n1 = yes, 2 = no",
        "pcm": "We fit use your voice notes and your corrections to make speech recognition better? Dis one no concern your report.\n1 = yes, 2 = no",  # needs native review
    },
    "report.limit_reached": {
        "fr": "Vous avez atteint la limite de {n} signalements par jour. Merci de réessayer demain.",
        "en": "You have reached the limit of {n} reports per day. Please try again tomorrow.",
        "pcm": "You don reach di limit of {n} reports for one day. Abeg try again tomorrow.",  # needs native review
    },
    "report.submitted": {
        "fr": "✅ Merci, votre signalement est enregistré. Référence : {reference}\nIl attend la relecture du modérateur (en général sous {hours} h). Nous vous écrirons ici dès qu'il y aura une décision.",
        "en": "✅ Thank you, your report is recorded. Reference: {reference}\nIt is waiting for review by the moderator (usually within {hours} hours). We will message you here as soon as there is an outcome.",
        "pcm": "✅ Thank you, your report don enter. Reference: {reference}\nE dey wait for moderator to check am (usually inside {hours} hours). We go message you here when decision dey.",  # needs native review
    },
}

DEFAULT_LANG = "fr"


def t(key: str, lang: str | None, **fmt: object) -> str:
    """Look up copy for `key`, falling back to French. Unknown keys and missing fmt args raise."""
    entry = CATALOG[key]
    text = entry.get(lang or DEFAULT_LANG) or entry[DEFAULT_LANG]
    # str.format raises KeyError on a missing argument; that is deliberate, never swallow it.
    return text.format(**fmt)
