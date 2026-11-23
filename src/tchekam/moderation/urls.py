from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("", views.queue, name="queue"),
    path("reports/<int:report_id>/", views.review, name="review"),
    path("reports/<int:report_id>/save/", views.save, name="save"),
    path("reports/<int:report_id>/decide/", views.decide, name="decide"),
    path("reports/<int:report_id>/reveal/", views.reveal, name="reveal"),
    path("evidence/<int:evidence_id>/", views.evidence, name="evidence"),
]
