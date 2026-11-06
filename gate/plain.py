"""The report's plain-language wording, one row per rule id and one per error code. Rows are written for someone
who has never heard of WCAG: name the HTML to change, not the standard. Keys are checked against the vendored axe
and the walker in tests/test_plain.py."""

# rule_id -> (the problem, what to do). The problem has no full stop: the report shows it as a bold title.
# What to do is one sentence.
PLAIN: dict[str, tuple[str, str]] = {
    "image-alt": (
        "Images have no text description",
        "Add an `alt` attribute to each `<img>` that says what it shows, or `alt=\"\"` (empty on purpose) if it is "
        "only decoration."),
    "input-image-alt": (
        "Image buttons have no text description",
        "Add an `alt` attribute to each `<input type=\"image\">` that says what the button does, such as "
        "`alt=\"Search\"`."),
    "area-alt": (
        "Clickable parts of an image map have no text description",
        "Add an `alt` attribute to each `<area>` that says where it goes."),
    "svg-img-alt": (
        "SVG graphics have no text description",
        "Add a `<title>` inside each `<svg role=\"img\">` that says what it shows, or for decoration remove the "
        "`role=\"img\"` and add `aria-hidden=\"true\"`."),
    "role-img-alt": (
        "Elements marked as images have no text description",
        "Add an `aria-label` that says what it shows to each element with `role=\"img\"`, or for decoration remove "
        "the `role` and add `aria-hidden=\"true\"`."),
    "object-alt": (
        "Embedded objects have no text description",
        "Add an `aria-label` or a `title` to each `<object>` that says what it shows, or put fallback text inside "
        "it."),
    "link-name": (
        "Links have no text a screen reader can read",
        "Put readable text inside each `<a>` that says where it goes, or for an icon-only link add an `aria-label` "
        "such as `aria-label=\"Home\"`."),
    "button-name": (
        "Buttons have no text a screen reader can read",
        "Put readable text inside each `<button>` that says what it does, or for an icon-only button add an "
        "`aria-label` such as `aria-label=\"Close\"`."),
    "label": (
        "Form fields have no label",
        "Give each field a `<label>` whose `for` matches the field's `id` (or wrap the field in the `<label>`), or "
        "add an `aria-label` if there is no room for visible text."),
    "select-name": (
        "Dropdown menus have no label",
        "Give each `<select>` a `<label>` whose `for` matches its `id`, or add an `aria-label`."),
    "input-button-name": (
        "Buttons made with `<input>` have no text",
        "Give each `<input type=\"button\">`, `type=\"submit\"` or `type=\"reset\"` a non-empty `value` that says "
        "what it does, such as `value=\"Search\"`."),
    "color-contrast": (
        "Text is too faint against its background",
        "Darken the text colour or lighten the background until the contrast ratio is at least 4.5 to 1 (3 to 1 for "
        "large text), which the colour picker in your browser's developer tools shows."),
    "html-has-lang": (
        "The page does not say what language it is in",
        "Add a `lang` attribute to the `<html>` tag, such as `<html lang=\"en\">`."),
    "html-lang-valid": (
        "The page's language code is not valid",
        "Change the `lang` attribute on `<html>` to a real language code, such as `en` or `fr`."),
    "valid-lang": (
        "A language code inside the page is not valid",
        "Change the `lang` attribute on that element to a real language code, such as `es` or `de`."),
    "document-title": (
        "The page has no title",
        "Add a short `<title>` inside `<head>` that says what the page is about."),
    "frame-title": (
        "Embedded frames have no title",
        "Add a `title` attribute to each `<iframe>` that says what it contains."),
    "aria-required-attr": (
        "A custom control is missing attributes that screen readers need",
        "Add the `aria-` attributes its `role` requires (a `role=\"checkbox\"` needs `aria-checked`), or switch to "
        "a standard element such as `<input type=\"checkbox\">`."),
    "aria-valid-attr": (
        "A screen reader attribute has a name that does not exist",
        "Fix the spelling of the `aria-` attribute (`aria-lable` should be `aria-label`), or remove it."),
    "aria-valid-attr-value": (
        "A screen reader attribute has a value that is not allowed",
        "Fix the value of the `aria-` attribute, for example by pointing `aria-labelledby` at an `id` that exists or "
        "setting `aria-expanded` to `true` or `false`."),
    "aria-roles": (
        "An element has a role that does not exist",
        "Change the `role` attribute to a real role such as `button` or `dialog`, or remove it."),
    "aria-allowed-attr": (
        "A screen reader attribute is used where it does not apply",
        "Remove the `aria-` attribute from that element, or change the element's `role` to one that supports it."),
    "aria-hidden-focus": (
        "Content hidden from screen readers can still be reached with the keyboard",
        "Remove `aria-hidden=\"true\"` from the element, or add `tabindex=\"-1\"` to every link, button and field "
        "inside it (`disabled` for form fields) so the keyboard skips them."),
    "aria-required-children": (
        "A custom widget is missing the parts it must contain",
        "Add the child elements its `role` requires, such as `role=\"listitem\"` inside `role=\"list\"` or "
        "`role=\"tab\"` inside `role=\"tablist\"`."),
    "aria-required-parent": (
        "A custom widget part is outside the element that must contain it",
        "Move it inside the parent its `role` requires, such as `role=\"listitem\"` inside `role=\"list\"` or "
        "`role=\"tab\"` inside `role=\"tablist\"`."),
    "list": (
        "A list is built incorrectly",
        "Make sure a `<ul>` or `<ol>` contains only `<li>` items directly, by moving anything else inside an `<li>` "
        "or out of the list."),
    "listitem": (
        "A list item is not inside a list",
        "Wrap each `<li>` in a `<ul>` or `<ol>`, or use a different tag if it is not part of a list."),
    "definition-list": (
        "A description list is built incorrectly",
        "Make sure a `<dl>` contains only `<dt>` and `<dd>` elements (optionally grouped in `<div>`), and move "
        "anything else out of it."),
    "dlitem": (
        "Description list items are outside a description list",
        "Put each `<dt>` and `<dd>` inside a `<dl>`."),
    "duplicate-id-aria": (
        "Two elements share an id that a label or screen reader attribute points to",
        "Give each element its own `id` and update the `for`, `aria-labelledby` or `aria-describedby` that refers "
        "to it."),
    "meta-viewport": (
        "The page stops visitors zooming in",
        "In `<meta name=\"viewport\">`, remove `user-scalable=no` and remove `maximum-scale` or set it to at "
        "least 2."),
    "meta-refresh": (
        "The page reloads or redirects itself after a delay",
        "Remove the timed `<meta http-equiv=\"refresh\">` and redirect on the server instead, or use a delay of 0."),
    "target-size": (
        "Buttons or links are too small or too close together to press reliably",
        "Make each one at least 24 by 24 pixels, or leave 24 pixels of space around it, using `min-width`, "
        "`min-height` or `padding`."),
    "td-headers-attr": (
        "A table cell points to a header that does not exist",
        "Make every id in the cell's `headers` attribute match the `id` of a `<th>` in the same table, or remove "
        "`headers`."),
    "th-has-data-cells": (
        "A table header has no data cells to describe",
        "Make sure each `<th>` has data cells under or beside it, or change it to a `<td>` if it is not a header."),
    "autocomplete-valid": (
        "A form field's autocomplete hint is not valid",
        "Change the `autocomplete` attribute to a valid value such as `email`, `name` or `postal-code`, or remove "
        "it."),
    "form-field-multiple-labels": (
        "A form field has more than one label",
        "Keep one `<label>` for the field and remove the extra `<label>` elements that point at it."),
    "link-in-text-block": (
        "Links inside text are only told apart by colour",
        "Underline links inside paragraphs with `text-decoration: underline`, or give them another visible "
        "difference such as bold."),
    "nested-interactive": (
        "A button or link contains another button, link or field",
        "Move any link, button or field out of an element that is itself a button (a `<button>` or "
        "`role=\"button\"`), so each control stands alone."),
    "scrollable-region-focusable": (
        "A scrolling area cannot be reached with the keyboard",
        "Add `tabindex=\"0\"` to the scrolling element, or make sure it contains a link, button or field."),
    "video-caption": (
        "Videos have no captions",
        "Add a `<track kind=\"captions\" src=\"...\">` to each `<video>` so people who cannot hear it can read what "
        "is said."),
    "audio-caption": (
        "Audio has no captions",
        "Add a `<track kind=\"captions\" src=\"...\">` to each `<audio>` so people who cannot hear it can read what "
        "is said."),
    "label-content-name-mismatch": (
        "A control's spoken name does not contain the words shown on it",
        "Make its `aria-label` start with the text shown on it, or remove the `aria-label` (a button showing "
        "\"Support our mission\" should not say `aria-label=\"Donate\"`)."),
    "bypass": (
        "There is no way to skip the menu and jump to the main content",
        "Wrap the main content in a `<main>` element, or add a \"Skip to content\" link at the top of the page that "
        "points to it."),
    "aria-command-name": (
        "Custom buttons or links have no readable name",
        "Put text inside the element, or add an `aria-label`, that says what it does."),
    "aria-input-field-name": (
        "Custom input fields have no label",
        "Add an `aria-label` or `aria-labelledby` that says what the field is for to each element with a role such "
        "as `textbox`, `combobox` or `slider`."),
    "aria-prohibited-attr": (
        "A screen reader attribute is used where it is not allowed",
        "Remove the `aria-label` or `aria-labelledby` from plain `<div>` or `<span>` elements, or give the element "
        "a `role` that can have a name."),
    "aria-hidden-body": (
        "The whole page is hidden from screen readers",
        "Remove `aria-hidden=\"true\"` from the `<body>` tag."),
    "frame-title-unique": (
        "Two frames have the same title",
        "Give each `<iframe>` its own `title` that says what it contains."),
    "summary-name": (
        "An expandable section has no label",
        "Put text inside each `<summary>` that says what the section contains."),
    "html-xml-lang-mismatch": (
        "The page's two language settings disagree",
        "Make `lang` and `xml:lang` on `<html>` name the same language, or remove `xml:lang`."),
    "td-has-header": (
        "Cells in a large data table have no header",
        "Add a `<th>` header for each column or row, so every data cell has one."),
    "focus-not-visible": (
        "Keyboard focus cannot be seen on some elements",
        "Give the element a visible focus style such as `:focus-visible { outline: 2px solid; }`, and replace any "
        "`outline: none` with another visible style."),
    "kbd-trap": (
        "Keyboard focus gets stuck",
        "Make sure Tab and Shift+Tab can always move on from this element, by checking any script that handles keys "
        "or moves focus back to it."),
    "modal-focus-escape": (
        "Keyboard focus leaves an open dialog",
        "Keep Tab inside an open dialog and close it with the Escape key, which the native `<dialog>` element with "
        "`showModal()` does for you."),
}

UNMAPPED_TODO = "Search for the rule name {rule} to see how to fix it."

# error code -> what happened and what to try. The report adds the raw code after it, for support.
ERRORS: dict[str, str] = {
    "too_large": "The page's main HTML is over 2 MB, the limit Tabitha can load. Try a page with less HTML, or a "
                 "lighter section of the site.",
    "timeout": "The page took too long to load and scan (the limit is 30 seconds), so Tabitha stopped. Try again in "
               "a minute, and check that the page opens quickly in a normal browser.",
    "blocked": "Tabitha could not reach that address, or is not allowed to. It only tests public web pages, so "
               "private or local addresses and pages behind a login will not work. Check the address and try again.",
    "scan_tampered": "The page interfered with the scan, so Tabitha cannot trust any result from it. Try again; if "
                     "it keeps happening, the page is blocking automated checks.",
    "internal_error": "Something went wrong while loading or scanning the page, and Tabitha could not tell what. "
                      "Try again in a minute, and check that the page opens in a normal browser.",
    "bad_request": "Tabitha did not understand that address. Send one public web address that starts with http:// "
                   "or https:// and is at most 2048 characters long.",
    "quota_exceeded": "The free scans for today (5 per UTC day) are used up. They start again at 00:00 UTC.",
    "busy": "Tabitha is running other scans right now. Try again in a minute. This attempt did not use up one of "
            "your free scans.",
    "payment_required": "Patches are paid, so nothing ran. Send `check <url>` for a free scan, or `fix <url>` to see "
                        "how to pay for a patch.",
}
GENERIC_ERROR = "The scan did not complete, and Tabitha has no more detail. Try again in a minute."
