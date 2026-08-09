from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from .forms import TradingAccountForm
from .models import TradingAccount


class TradingAccountListView(LoginRequiredMixin, ListView):
    """List all trading accounts belonging to the current user."""

    model = TradingAccount
    template_name = "tradingaccount_list.html"
    context_object_name = "accounts"

    def get_queryset(self):
        return TradingAccount.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["threshold"] = TradingAccount.INACTIVITY_THRESHOLD_DAYS
        return context


class TradingAccountDetailView(LoginRequiredMixin, DetailView):
    """Show a single account with a large countdown clock."""

    model = TradingAccount
    template_name = "tradingaccount_detail.html"
    context_object_name = "account"

    def get_queryset(self):
        return TradingAccount.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["threshold"] = TradingAccount.INACTIVITY_THRESHOLD_DAYS
        # JS-friendly ISO timestamp of the inactivity deadline
        context["deadline"] = self.object.deadline_iso()
        return context


class TradingAccountCreateView(LoginRequiredMixin, CreateView):
    """Create a new trading account for the current user."""

    model = TradingAccount
    form_class = TradingAccountForm
    template_name = "tradingaccount_form.html"
    success_url = reverse_lazy("trades:list")

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


class TradingAccountUpdateView(LoginRequiredMixin, UpdateView):
    """Edit an existing trading account."""

    model = TradingAccount
    form_class = TradingAccountForm
    template_name = "tradingaccount_form.html"

    def get_queryset(self):
        return TradingAccount.objects.filter(user=self.request.user)

    def get_success_url(self):
        return reverse_lazy("trades:detail", kwargs={"pk": self.object.pk})


class TradingAccountDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a trading account."""

    model = TradingAccount
    template_name = "tradingaccount_confirm_delete.html"
    success_url = reverse_lazy("trades:list")
    context_object_name = "account"

    def get_queryset(self):
        return TradingAccount.objects.filter(user=self.request.user)
