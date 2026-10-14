import csv
import io
import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils.timezone import now
from django_scopes import scopes_disabled
from eventyay.base.models import Order, OrderPosition, Product, Team, Voucher
from eventyay.base.models.auth import User

from exhibition import mail as mail_helpers
from exhibition.models import (
    ExhibitionAnswer,
    ExhibitionEmailQueue,
    ExhibitionQuestion,
    ExhibitionQuestionOption,
    ExhibitionQuestionVariant,
    ExhibitionRequest,
    ExhibitionRequestState,
    ExhibitorExtraLink,
    ExhibitorInfo,
    ExhibitorSocialLink,
    ExhibitorVoucher,
    Lead,
)

_codes = itertools.count(1)
OLD_COLUMNS = ["Name", "Booth ID", "Booth name", "Email", "Access key"]


@pytest.fixture(autouse=True)
def _organizer_pages(settings):
    """Render the organizer pages the way the other organizer list tests do."""
    settings.DEBUG = True
    settings.COMPRESS_ENABLED = False
    settings.COMPRESS_PRECOMPILERS = ()


def _organization(event, name, **kwargs):
    kwargs.setdefault("is_exhibitor", True)
    return ExhibitorInfo.objects.create(event=event, name=name, email=f"{name.lower()}@example.com", **kwargs)


def _client(event, **flags):
    with scopes_disabled():
        event.plugins = "exhibition"
        event.save(update_fields=["plugins"])
        user = User.objects.create_user(email=f"team-{next(_codes)}@example.com", password="pw")
        team = Team.objects.create(
            organizer=event.organizer, all_events=True, **(flags or {"can_change_event_settings": True})
        )
        team.members.add(user)
    client = Client()
    client.force_login(user)
    return client


def _download(client, event, query="", name="exhibitors"):
    url = reverse(f"plugins:exhibition:{name}", kwargs={"organizer": event.organizer.slug, "event": event.slug})
    return client.get(url + "?download=yes" + query)


def _rows(response):
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert content.startswith("\ufeff")
    rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))
    header, *body = rows
    return [dict(zip(header, row)) for row in body], header


@pytest.mark.django_db
def test_download_keeps_the_columns_of_the_old_key_download(event):
    with scopes_disabled():
        acme = _organization(event, "Acme", booth_id="A1", booth_name={"en": "Privacy Lounge"})
    rows, header = _rows(_download(_client(event), event))

    assert header[:1] == ["Name"] and all(column in header for column in OLD_COLUMNS)
    assert [{column: row[column] for column in OLD_COLUMNS} for row in rows] == [
        {
            "Name": "Acme",
            "Booth ID": "A1",
            "Booth name": "Privacy Lounge",
            "Email": "acme@example.com",
            "Access key": acme.key,
        }
    ]


@pytest.mark.django_db
def test_download_has_a_column_for_every_group(event):
    with scopes_disabled():
        _organization(event, "Acme")
        ExhibitionQuestion.objects.create(event=event, question={"en": "Booth size"}, position=1)
    _rows_, header = _rows(_download(_client(event), event))

    for column in (
        "Description",
        "Website",
        "Contact page URL",
        "Logo",
        "Banner",
        "Video",
        "Slides",
        "Social media links",
        "Additional links",
        "Related sessions",
        "Type",
        "Sponsor group",
        "Published",
        "Active",
        "Position on the public exhibitor page",
        "Lead scanning enabled",
        "Voucher access",
        "Lead access",
        "Lead scanning limited to registered devices",
        "Registered scanning devices",
        "Vouchers assigned",
        "Vouchers claimed",
        "Voucher state",
        "Vouchers last sent",
        "Leads scanned",
        "Request date",
        "Applicant name",
        "Applicant email",
        "Booth size",
    ):
        assert column in header, column


@pytest.mark.django_db
def test_several_links_share_one_cell_one_per_line(event):
    with scopes_disabled():
        acme = _organization(event, "Acme")
        for network in ("facebook", "flickr", "github"):
            ExhibitorSocialLink.objects.create(exhibitor=acme, network=network, url=f"https://{network}.com/acme")
        ExhibitorExtraLink.objects.create(exhibitor=acme, label="Press kit", url="https://acme.example/press")
    rows, _header = _rows(_download(_client(event), event))

    assert rows[0]["Social media links"].split("\n") == [
        "Facebook: https://facebook.com/acme",
        "Flickr: https://flickr.com/acme",
        "GitHub: https://github.com/acme",
    ]
    assert rows[0]["Additional links"] == "Press kit: https://acme.example/press"


@pytest.mark.django_db
def test_application_columns_come_from_the_accepted_request(event):
    with scopes_disabled():
        size = ExhibitionQuestion.objects.create(event=event, question={"en": "Booth size"}, position=1)
        power = ExhibitionQuestion.objects.create(
            event=event, question={"en": "Power"}, variant=ExhibitionQuestionVariant.MULTIPLE, position=2
        )
        plan = ExhibitionQuestion.objects.create(
            event=event, question={"en": "Floor plan"}, variant=ExhibitionQuestionVariant.FILE, position=3
        )
        options = [
            ExhibitionQuestionOption.objects.create(question=power, answer={"en": label}) for label in ("230V", "USB")
        ]
        applied = _organization(event, "Applied")
        _organization(event, "Manual")
        applicant = User.objects.create_user(email="dana@example.com", password="pw", fullname="Dana Scully")
        request = ExhibitionRequest.objects.create(
            event=event,
            user=applicant,
            name="Applied",
            state=ExhibitionRequestState.ACCEPTED,
            submitted=now(),
            approved_exhibitor=applied,
        )
        ExhibitionAnswer.objects.create(question=size, exhibition_request=request, answer="Large")
        ExhibitionAnswer.objects.create(question=power, exhibition_request=request).options.set(options)
        ExhibitionAnswer.objects.create(
            question=plan, exhibition_request=request, file=SimpleUploadedFile("plan.pdf", b"%PDF-1.4")
        )
    rows, _header = _rows(_download(_client(event), event))
    by_name = {row["Name"]: row for row in rows}

    assert by_name["Applied"]["Request date"]
    assert by_name["Applied"]["Applicant name"] == "Dana Scully"
    assert by_name["Applied"]["Applicant email"] == "dana@example.com"
    assert by_name["Applied"]["Booth size"] == "Large"
    assert by_name["Applied"]["Power"].split("\n") == ["230V", "USB"]
    assert by_name["Applied"]["Floor plan"].startswith("http://testserver/")
    assert by_name["Applied"]["Floor plan"].endswith(".pdf")
    for column in ("Request date", "Applicant name", "Applicant email", "Booth size", "Power", "Floor plan"):
        assert by_name["Manual"][column] == ""


@pytest.mark.django_db
def test_voucher_and_lead_columns_match_the_list(event):
    with scopes_disabled():
        acme = _organization(event, "Acme")
        product = Product.objects.create(event=event, name="Ticket", default_price=10, active=True)
        vouchers = [Voucher.objects.create(event=event, product=product, code=f"CODE{index}") for index in range(5)]
        for voucher in vouchers:
            ExhibitorVoucher.objects.create(exhibitor=acme, voucher=voucher)
        for voucher in vouchers[:2]:
            order = Order.objects.create(
                code=f"O{next(_codes):04d}",
                event=event,
                email="attendee@example.com",
                status=Order.STATUS_PAID,
                datetime=now(),
                expires=now() + timedelta(days=10),
                total=Decimal("0.00"),
                locale="en",
            )
            OrderPosition.objects.create(order=order, product=product, price=Decimal("0"), voucher=voucher)
        ExhibitionEmailQueue.objects.create(
            event=event,
            exhibitor=acme,
            role=mail_helpers.VOUCHERS,
            to_email="acme@example.com",
            subject="Vouchers",
            body="Codes",
            sent_at=now(),
        )
        for index in range(3):
            Lead.objects.create(
                exhibitor=acme,
                exhibitor_name="Acme",
                pseudonymization_id=f"P{index}",
                scanned=now(),
                scan_type="lead",
                device_name="Phone",
                booth_id="A1",
                booth_name="Lounge",
            )
    rows, _header = _rows(_download(_client(event), event))

    assert rows[0]["Vouchers assigned"] == "5"
    assert rows[0]["Vouchers claimed"] == "2"
    assert rows[0]["Voucher state"] == "Partly claimed"
    assert rows[0]["Vouchers last sent"]
    assert rows[0]["Leads scanned"] == "3"
    assert rows[0]["Registered scanning devices"] == "0"


@pytest.mark.django_db
def test_download_holds_the_selection_or_every_filtered_row(event):
    with scopes_disabled():
        first, second, third, fourth = (_organization(event, name) for name in ("Ann", "Bob", "Cid", "Dee"))
        fourth.published = True
        fourth.save(update_fields=["published"])
    client = _client(event)

    selected, _header = _rows(_download(client, event, f"&pk={first.pk}&pk={second.pk}&pk={third.pk}"))
    filtered, _header = _rows(_download(client, event, "&published=1"))
    everyone, _header = _rows(_download(client, event))

    assert [row["Name"] for row in selected] == ["Ann", "Bob", "Cid"]
    assert [row["Name"] for row in filtered] == ["Dee"]
    assert len(everyone) == 4


@pytest.mark.django_db
def test_file_name_has_the_event_and_the_date(event):
    response = _download(_client(event), event)

    expected = f'attachment; filename="{event.slug}-exhibitors-{now().astimezone(event.tz).date().isoformat()}.csv"'
    assert response["Content-Disposition"] == expected


@pytest.mark.django_db
def test_download_needs_the_event_settings_permission(event):
    client = _client(event, can_view_orders=True)
    with scopes_disabled():
        _organization(event, "Acme")
    url = reverse("plugins:exhibition:exhibitors", kwargs={"organizer": event.organizer.slug, "event": event.slug})

    assert client.get(url + "?download=yes").status_code == 403
    assert "Download exhibitors" not in client.get(url).content.decode()


@pytest.mark.django_db
def test_list_offers_download_exhibitors_instead_of_keys(event):
    client = _client(event)
    with scopes_disabled():
        _organization(event, "Acme")
    url = reverse("plugins:exhibition:exhibitors", kwargs={"organizer": event.organizer.slug, "event": event.slug})
    html = client.get(url).content.decode()

    assert "Download exhibitors" in html
    assert "Download exhibitor keys" not in html


@pytest.mark.django_db
def test_formula_like_values_cannot_run_as_formulas(event):
    with scopes_disabled():
        question = ExhibitionQuestion.objects.create(event=event, question={"en": "Notes"}, position=1)
        sneaky = _organization(
            event, '=HYPERLINK("https://evil.example","click")', description={"en": "+1+1"}, booth_name={"en": "\t=1"}
        )
        request = ExhibitionRequest.objects.create(
            event=event,
            user=User.objects.create_user(email="sneaky@example.com", password="pw"),
            name="Sneaky",
            state=ExhibitionRequestState.ACCEPTED,
            submitted=now(),
            approved_exhibitor=sneaky,
        )
        ExhibitionAnswer.objects.create(question=question, exhibition_request=request, answer="@SUM(A1:A9)")
    rows, _header = _rows(_download(_client(event), event))

    assert rows[0]["Name"] == '\'=HYPERLINK("https://evil.example","click")'
    assert rows[0]["Description"] == "'+1+1"
    assert rows[0]["Booth name"] == "'\t=1"
    assert rows[0]["Notes"] == "'@SUM(A1:A9)"


@pytest.mark.django_db
def test_answers_are_exported_in_the_event_default_language(event):
    with scopes_disabled():
        event.settings.locale = "de"
        event.settings.locales = ["de", "en"]
        power = ExhibitionQuestion.objects.create(
            event=event, question={"de": "Strom", "en": "Power"}, variant=ExhibitionQuestionVariant.BOOLEAN, position=1
        )
        acme = _organization(event, "Acme")
        request = ExhibitionRequest.objects.create(
            event=event,
            user=User.objects.create_user(email="acme-applicant@example.com", password="pw"),
            name="Acme",
            state=ExhibitionRequestState.ACCEPTED,
            submitted=now(),
            approved_exhibitor=acme,
        )
        ExhibitionAnswer.objects.create(question=power, exhibition_request=request, answer="True")
    client = _client(event)
    client.cookies["django_language"] = "en"

    rows, _header = _rows(_download(client, event))
    values = list(rows[0].values())

    # The organizer browses in English, but the file follows the event's default language.
    assert rows[0]["Strom"] == "Ja"
    assert "Nein" in values
    assert "Yes" not in values and "No" not in values
