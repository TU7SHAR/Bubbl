/**
 * Client-side advisory check for custom lead field names.
 *
 * The server is authoritative: utils/lead_fields.py drops reserved and
 * duplicate names on save regardless of what happens here. This exists
 * only so an admin finds out while typing instead of discovering it in
 * a flash message after a full page submit.
 *
 * The reserved list is NOT redefined here. It arrives as
 * window.BUBBL_RESERVED_FIELD_NAMES, injected from RESERVED_FIELD_NAMES
 * in utils/lead_fields.py by the reserved_lead_field_names template
 * global, so the browser and the server cannot disagree.
 *
 * Shared by both the Edit Bot page and the Create Bot page.
 */
(function () {
  'use strict';

  /** Mirror of field_identity() in utils/lead_fields.py. */
  function identity(name) {
    return String(name == null ? '' : name)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  function reservedSet() {
    var list = window.BUBBL_RESERVED_FIELD_NAMES;
    return Array.isArray(list) ? list : [];
  }

  /**
   * Why `fields[index].name` will not be saved, or null if it is fine.
   *
   * Mirrors the order normalize_custom_fields() applies: reserved wins
   * over duplicate, and only earlier rows count as "above it".
   */
  function rejectionReason(fields, index) {
    if (!Array.isArray(fields) || !fields[index]) return null;

    var key = identity(fields[index].name);
    if (!key) return null;

    if (reservedSet().indexOf(key) !== -1) {
      return 'Name, Email and Phone are already collected. This field will not be saved.';
    }

    for (var i = 0; i < index; i++) {
      if (fields[i] && identity(fields[i].name) === key) {
        return 'Duplicate of a field above. This field will not be saved.';
      }
    }

    return null;
  }

  /**
   * Show or clear the warning for one row.
   *
   * Expects the row wrapper to contain [data-field-warning] and the
   * name input to be [data-field-name-input], both emitted by
   * renderCustomFields() on each page.
   */
  function applyWarning(container, fields, index) {
    if (!container) return;

    var row = container.querySelector('[data-field-row="' + index + '"]');
    if (!row) return;

    var slot = row.querySelector('[data-field-warning]');
    var input = row.querySelector('[data-field-name-input]');
    var reason = rejectionReason(fields, index);

    if (slot) {
      slot.textContent = reason || '';
      slot.style.display = reason ? 'block' : 'none';
    }
    if (input) {
      input.style.borderColor = reason ? '#ef4444' : 'rgba(0,0,0,0.1)';
    }
  }

  /** Re-check every row. Call after add/remove/rename. */
  function applyAllWarnings(container, fields) {
    if (!Array.isArray(fields)) return;
    for (var i = 0; i < fields.length; i++) {
      applyWarning(container, fields, i);
    }
  }

  window.BubblLeadFields = {
    identity: identity,
    rejectionReason: rejectionReason,
    applyWarning: applyWarning,
    applyAllWarnings: applyAllWarnings
  };
})();
