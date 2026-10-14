"""The organizations spreadsheet behind the "Download exhibitors" button on the organizer lists."""

import io

from defusedcsv import csv
from django.db.models import Count, Prefetch
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django_scopes import scope

from .models import (
    QUESTION_OPTION_VARIANTS,
    ExhibitionAnswer,
    ExhibitionQuestion,
    ExhibitionQuestionVariant,
    ExhibitionRequest,
    ExhibitorDevice,
    ExhibitorInfo,
    Lead,
    OrganizationVoucherState,
)
from .utils import localized_value_for, public_exhibitors_queryset

FILE_KINDS = {"exhibitor": "exhibitors", "sponsor": "sponsors"}


def organizations_csv_filename(event, organization_type):
    """``<event>-exhibitors-<date>.csv``, named after the list it was downloaded from."""
    kind = FILE_KINDS.get(organization_type, "organizations")
    return f"{event.slug}-{kind}-{timezone.now().astimezone(event.tz).date().isoformat()}.csv"


def build_organizations_csv(request, organizations) -> str:
    """Everything stored about each organization, one row each, in the order given.

    ``organizations`` must be annotated by ``utils.with_voucher_state``, so the voucher columns
    match the Vouchers column of the list. Text in several languages is exported in the
    event's default language, fields with several values are one cell with a value per line,
    and uploaded files are absolute links. Empty values stay blank.
    """
    organizations = list(
        organizations.select_related("sponsor_group").prefetch_related(
            "social_links",
            "extra_links",
            Prefetch(
                "source_requests",
                queryset=ExhibitionRequest.objects.select_related("user").prefetch_related(
                    Prefetch(
                        "answers",
                        queryset=ExhibitionAnswer.objects.select_related("question").prefetch_related("options"),
                    )
                ),
            ),
        )
    )
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC, delimiter=",")
    # Labels, Yes/No and country names follow the event's default language, like the data does.
    with translation.override(request.event.settings.locale):
        exporter = _Exporter(request, organizations)
        writer.writerow([_safe_cell(value) for value in exporter.headers()])
        for organization in organizations:
            writer.writerow([_safe_cell(value) for value in exporter.row(organization)])
    # The byte order mark makes Excel read the file as UTF-8; LibreOffice and Sheets ignore it.
    return "\ufeff" + output.getvalue()


def _safe_cell(value):
    """Keep a spreadsheet from running a cell as a formula.

    defusedcsv already escapes cells starting with ``=``, ``+``, ``-`` or ``@``; a leading tab or
    carriage return can start a formula too, so those are escaped the same way.
    """
    if isinstance(value, str) and value[:1] in ("\t", "\r"):
        return "'" + value
    return value


class _Exporter:
    def __init__(self, request, organizations):
        self.request = request
        self.event = request.event
        self.locale = self.event.settings.locale
        pks = [organization.pk for organization in organizations]
        self.questions = list(ExhibitionQuestion.objects.filter(event=self.event).order_by("position", "id"))
        self.lead_counts = self._counts(Lead, pks)
        self.device_counts = self._counts(ExhibitorDevice, pks)
        # Numbered from the public page's own queryset, so hidden organizations get no position.
        shown = public_exhibitors_queryset(self.event).prefetch_related(None).values_list("pk", flat=True)
        self.positions = {pk: index for index, pk in enumerate(shown, 1)}
        with scope(event=self.event):
            sessions = ExhibitorInfo.sessions.through.objects.filter(exhibitorinfo_id__in=pks).select_related(
                "submission"
            )
            self.sessions = {}
            for link in sessions.order_by("submission__title"):
                self.sessions.setdefault(link.exhibitorinfo_id, []).append(link.submission.title)

    @staticmethod
    def _counts(model, pks):
        rows = model.objects.filter(exhibitor_id__in=pks).values_list("exhibitor_id").annotate(count=Count("pk"))
        return dict(rows)

    def headers(self):
        return [
            # Organization
            _("Name"),
            _("Description"),
            _("Website"),
            _("Contact page URL"),
            _("Email"),
            _("Logo"),
            _("Banner"),
            _("Video"),
            _("Slides"),
            _("Social media links"),
            _("Additional links"),
            _("Related sessions"),
            # Status
            _("Type"),
            _("Sponsor group"),
            _("Published"),
            _("Active"),
            _("Position on the public exhibitor page"),
            # Booth
            _("Booth ID"),
            _("Booth name"),
            # Access and app
            _("Access key"),
            _("Lead scanning enabled"),
            _("Voucher access"),
            _("Lead access"),
            _("Lead scanning limited to registered devices"),
            _("Registered scanning devices"),
            # Vouchers
            _("Vouchers assigned"),
            _("Vouchers claimed"),
            _("Voucher state"),
            _("Vouchers last sent"),
            # Leads
            _("Leads scanned"),
            # Application
            _("Request date"),
            _("Applicant name"),
            _("Applicant email"),
            *(self.text(question.question) for question in self.questions),
        ]

    def row(self, organization):
        application = self.application(organization)
        answers = {answer.question_id: answer for answer in application.answers.all()} if application else {}
        applicant = application.user if application and application.user_id else None
        return [
            self.text(organization.name),
            self.text(organization.description),
            organization.url or "",
            organization.contact_url or "",
            organization.recipient_email,
            self.link(organization.visible_logo_url),
            self.link(organization.visible_banner_url),
            organization.video_url or "",
            self.link(organization.visible_slides_url),
            self.lines(str(link) for link in organization.social_links.all()),
            self.lines(str(link) for link in organization.extra_links.all()),
            self.lines(self.sessions.get(organization.pk, ())),
            self.organization_type(organization),
            self.text(organization.sponsor_group.name) if organization.sponsor_group else "",
            self.yes_no(organization.published),
            self.yes_no(organization.active),
            self.positions.get(organization.pk, ""),
            organization.booth_id or "",
            organization.localized_booth_name,
            organization.key,
            self.yes_no(organization.lead_scanning_enabled),
            self.yes_no(organization.allow_voucher_access),
            self.yes_no(organization.allow_lead_access),
            self.yes_no(organization.lead_scanning_scope_by_device),
            self.device_counts.get(organization.pk, 0),
            organization.voucher_total,
            organization.voucher_claimed,
            str(OrganizationVoucherState(organization.voucher_state).label),
            self.when(organization.voucher_sent_at),
            self.lead_counts.get(organization.pk, 0),
            self.when(application.submitted if application else None),
            (applicant.fullname or "") if applicant else "",
            ((application.email or "").strip() or (applicant.email if applicant else "")) if application else "",
            *(self.answer(answers.get(question.pk)) for question in self.questions),
        ]

    @staticmethod
    def application(organization):
        """The request this organization was accepted from; the latest one if there are several."""
        requests = sorted(organization.source_requests.all(), key=lambda request: request.pk, reverse=True)
        return requests[0] if requests else None

    def answer(self, answer):
        if answer is None:
            return ""
        if answer.question.variant == ExhibitionQuestionVariant.FILE:
            return self.link(answer.file_url)
        if answer.question.variant in QUESTION_OPTION_VARIANTS:
            return self.lines(self.text(option.answer) for option in answer.options.all())
        return str(answer.answer_string)

    @staticmethod
    def organization_type(organization):
        if organization.is_exhibitor and organization.is_sponsor:
            return _("Exhibitor and sponsor")
        if organization.is_sponsor:
            return _("Sponsor")
        return _("Exhibitor")

    def text(self, value):
        return localized_value_for(value, self.locale)

    def link(self, url):
        return self.request.build_absolute_uri(url) if url else ""

    def when(self, value):
        return value.astimezone(self.event.tz).strftime("%Y-%m-%d %H:%M") if value else ""

    @staticmethod
    def yes_no(value):
        return _("Yes") if value else _("No")

    @staticmethod
    def lines(values):
        return "\n".join(value for value in values if value)
