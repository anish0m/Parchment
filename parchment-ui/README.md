# Parchment UI v2

Redesigned around the supplied periwinkle/lavender keyboard reference and Parchment logo.

- Periwinkle/lavender visual system with light and dark themes.
- Parchment logo used as favicon/browser thumbnail and page branding.
- Landing page has CSS motion/particle/orbit animation; the right-side artwork uses `assets/parchment-landing.png`, not the logo.
- No full-page phone/card layouts. Content uses the full viewport with restrained spacing.
- Navbar on authenticated pages: logo + project name left; username dropdown + theme toggle right.
- Profile page added with latest two courses and all-courses action.
- Course creation, material upload, flashcard creation and material processing are modal flows.
- Material upload/paste are tabs inside the Add Material modal, so only one input method is shown at a time.
- Processing state persists in localStorage for the prototype and can be closed while processing continues.
- Flashcards can only be displayed from processed materials; selecting a processing material opens the progress modal.
- Standalone course-add/material-add/material-processing pages were intentionally removed because those flows are now modals.

Django integration:
1. Move `parchment-theme.css` and `parchment.js` into static assets.
2. Move each page CSS/JS into the corresponding static folders.
3. Replace `.html` links with `{% url %}`.
4. Replace demo data with template context.
5. Replace demo modal handlers with Django forms/HTMX endpoints.
6. Replace the localStorage processing simulation with your Django-Q2 task status endpoint.
