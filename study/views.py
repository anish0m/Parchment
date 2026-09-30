import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from courses.models import Course
from flashcards.models import Flashcard
from materials.models import Material
from parchment.htmx import is_htmx

from .grading import MAX_ANSWER_LENGTH, grade_answer
from .models import StudySession
from .scheduler import (
    SessionError,
    already_answered,
    due_cards,
    end_session,
    next_card,
    record_answer,
    remaining_count,
    start_session,
)
from .stats import course_progress, session_summary


def _own_course(request, pk):
    return get_object_or_404(Course, pk=pk, owner=request.user)


def _own_session(request, pk):
    return get_object_or_404(
        StudySession.objects.select_related("course"), pk=pk, user=request.user
    )


def study_panel_context(course, now=None):
    """What the course page's Study panel needs: due count, next due date, empty states."""
    now = now or timezone.now()
    cards = course.flashcards
    card_count = cards.count()
    upcoming = cards.filter(next_review_at__gt=now).order_by("next_review_at").first()
    return {
        "course": course,
        "card_count": card_count,
        "box_average": cards.aggregate(average=Avg("box"))["average"] if card_count else None,
        "due_count": due_cards(course, now=now).count() if card_count else 0,
        "next_due": upcoming.next_review_at if upcoming else None,
        "generating": course.materials.filter(status__in=Material.IN_PROGRESS).exists(),
    }


def stage_context(session, now=None):
    """The card to show next, or (once there's none) the end-of-session summary."""
    now = now or timezone.now()
    card = next_card(session, now=now)
    if card is None:
        finished_early = session.is_active is False
        end_session(session, now=now)
        return {
            "session": session,
            "summary": session_summary(session, now=now),
            "finished_early": finished_early,
        }
    remaining = remaining_count(session, now=now)
    total = session.cards_reviewed + remaining
    return {
        "session": session,
        "card": card,
        "position": session.cards_reviewed + 1,
        "total": total,
        "progress": round(100 * session.cards_reviewed / total) if total else 0,
    }


def _render_stage(request, session):
    if is_htmx(request):
        return render(request, "study/partials/stage.html", stage_context(session))
    return redirect(session)


@login_required
@require_POST
def start(request, course_pk):
    course = _own_course(request, course_pk)
    mode = StudySession.Mode.PRACTICE if request.POST.get("mode") == "practice" else None
    if not course.flashcards.exists():
        messages.info(request, "This course has no flashcards to study yet.")
        return redirect(course)
    if mode is None and not due_cards(course).exists():
        messages.info(request, "Nothing is due right now. You can still study anyway.")
        return redirect(course)
    session = start_session(course, mode=mode or StudySession.Mode.DUE)
    return redirect(session)


@login_required
@require_GET
def session_view(request, pk):
    session = _own_session(request, pk)
    if is_htmx(request):  # "Next card"
        return render(request, "study/partials/stage.html", stage_context(session))
    return render(request, "study/session.html", stage_context(session))


def _session_card(request, session):
    card_pk = request.POST.get("card", "")
    return get_object_or_404(
        Flashcard, pk=int(card_pk) if card_pk.isdigit() else 0, course=session.course
    )


def _toast(level, title, message):
    return {"level": level, "title": title, "message": message}


def _result(request, session, card, *, correct, feedback="", given=None, skipped=False):
    """Record the answer and show it on the back of the card, with a toast.

    A repeat (double submit) or an answer after the session ended isn't recorded;
    the stage is shown as it is now instead.
    """
    if not session.is_active or already_answered(session, card):
        response = _render_stage(request, session)
        if is_htmx(request):
            response["HX-Retarget"] = "#study-stage"
            response["HX-Reswap"] = "innerHTML"
            response["HX-Trigger"] = json.dumps({"parchment:close-modal": {"id": "answer-modal"}})
        return response
    try:
        log = record_answer(card, correct, session=session)
    except SessionError as exc:
        return HttpResponseBadRequest(str(exc))
    if not is_htmx(request):
        return redirect(session)

    if skipped:
        toast = _toast("warning", "Skipped", "It counts as missed, so the card goes back to box 1.")
    elif correct:
        moved = (
            f"Moved up to box {log.box_after}." if log.was_promoted else "It stays in the top box."
        )
        toast = _toast("success", "Correct!", moved)
    else:
        toast = _toast(
            "danger", "Not quite", "The card goes back to box 1 so you'll see it again soon."
        )
    response = render(
        request,
        "study/partials/result.html",
        {
            "card": card,
            "log": log,
            "correct": correct,
            "skipped": skipped,
            "feedback": feedback,
            "given": given,
        },
    )
    response["HX-Trigger"] = json.dumps(
        {"parchment:toast": toast, "parchment:close-modal": {"id": "answer-modal"}}
    )
    return response


@login_required
@require_POST
def check(request, pk):
    """Check a typed answer, record whether it was right and turn the card over."""
    session = _own_session(request, pk)
    card = _session_card(request, session)
    given = request.POST.get("response", "").strip()[:MAX_ANSWER_LENGTH]
    if not given:
        return HttpResponseBadRequest("Type an answer first.")
    if not session.is_active or already_answered(session, card):
        return _result(request, session, card, correct=False)
    verdict = grade_answer(card, given)
    return _result(
        request, session, card, correct=verdict.correct, feedback=verdict.feedback, given=given
    )


@login_required
@require_POST
def skip(request, pk):
    """Show the answer without trying: counted as missed."""
    session = _own_session(request, pk)
    card = _session_card(request, session)
    return _result(request, session, card, correct=False, skipped=True)


@login_required
@require_POST
def end(request, pk):
    session = _own_session(request, pk)
    end_session(session)
    return _render_stage(request, session)


@login_required
@require_GET
def study_panel(request, course_pk):
    course = _own_course(request, course_pk)
    return render(request, "study/partials/study_panel.html", study_panel_context(course))


@login_required
@require_GET
def progress(request, course_pk):
    course = _own_course(request, course_pk)
    return render(request, "study/progress.html", {"course": course, **course_progress(course)})
