from django.urls import path

from . import appeal_views, views

app_name = "moderation"

urlpatterns = [
    path("", views.queue, name="queue"),
    path("reports/<int:report_id>/", views.review, name="review"),
    path("reports/<int:report_id>/save/", views.save, name="save"),
    path("reports/<int:report_id>/decide/", views.decide, name="decide"),
    path("reports/<int:report_id>/reveal/", views.reveal, name="reveal"),
    path("evidence/<int:evidence_id>/", views.evidence, name="evidence"),
    path("appeals/", appeal_views.queue, name="appeal_queue"),
    path("appeals/<int:appeal_id>/", appeal_views.review, name="appeal_review"),
    path("appeals/<int:appeal_id>/decide/", appeal_views.decide, name="appeal_decide"),
    path("appeal-evidence/<int:evidence_id>/", appeal_views.evidence, name="appeal_evidence"),
]
