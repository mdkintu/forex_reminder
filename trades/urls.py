from django.urls import path

from . import views

app_name = "trades"

urlpatterns = [
    path("", views.TradingAccountListView.as_view(), name="list"),
    path("add/", views.TradingAccountCreateView.as_view(), name="add"),
    path("<int:pk>/", views.TradingAccountDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.TradingAccountUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.TradingAccountDeleteView.as_view(), name="delete"),
]
