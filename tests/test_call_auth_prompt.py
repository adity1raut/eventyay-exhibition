import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django_scopes import scopes_disabled

from exhibition.models import ExhibitorSettings
from exhibition.views import PublicCallView, call_auth_urls


def make_call_settings(event):
    return ExhibitorSettings.objects.create(
        event=event,
        call_enabled=True,
        exhibitors_access_mail_subject="",
        exhibitors_access_mail_body="",
    )


def _call_view(event, user):
    view = PublicCallView()
    request = RequestFactory().get("/")
    request.event = event
    request.session = {}
    request.user = user
    view.request = request
    view.kwargs = {}
    return view


@pytest.mark.django_db
def test_auth_urls_return_to_the_request_form(event):
    with scopes_disabled():
        submit_url = reverse(
            "plugins:exhibition:proposal.add",
            kwargs={"organizer": event.organizer.slug, "event": event.slug},
        )
        urls = call_auth_urls(event)
        assert urls["call_login_url"].startswith(reverse("auth.login"))
        assert urls["call_register_url"].startswith(reverse("account_signup"))
        for url in urls.values():
            assert f"next={submit_url}" in url.replace("%2F", "/")


@pytest.mark.django_db
def test_anonymous_visitor_gets_auth_urls(event):
    with scopes_disabled():
        make_call_settings(event)
        context = _call_view(event, AnonymousUser()).get_context_data()
        assert context["call_login_url"]
        assert context["call_register_url"]
        assert "user_proposals" not in context


@pytest.mark.django_db
def test_logged_in_visitor_gets_no_auth_urls(event):
    from eventyay.base.models.auth import User

    with scopes_disabled():
        make_call_settings(event)
        user = User.objects.create_user(email="exhibitor@e.com", password="pw")
        context = _call_view(event, user).get_context_data()
        assert "call_login_url" not in context
        assert "call_register_url" not in context
        assert context["user_proposals"] is not None
