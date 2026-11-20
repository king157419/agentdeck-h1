# keymap v9 fixups (failing tests after Codex ran out of quota)

Classification: (a) test encoded v8 behaviour, updated to the v9 behaviour with the same safety checks; (b) production bug, fixed.

## test_hub.py
| Test | Class | Root cause | Change |
|---|---|---|---|
| test_desktop_actions_use_selected_session_and_bilingual_templates | a | `hub_controls` now calls `desktop.interrupt(..., layer=...)`; the fake `Desktop` in the test had the old signature. | test_hub.py: fake `Desktop.interrupt(self, session, sessions, layer=None)`. |
| test_decisions_audit_original_command_fields_and_sources_once | a | Approve moved from hid:0x0A (now ctx 1) to hid:0x2B (Tab). | test_hub.py: USB approve events use hid:0x2B; all audit fields/sources assertions unchanged. |
| test_hold_voice_blocks_approval_and_releases_on_usb_or_raw_device_removal (usb, raw) | a | Voice moved from hid:0x0B (H, now ctx 3) to ctrl+hid:0x19 (Ctrl+V). | test_hub.py: USB feeds Ctrl+V report; Raw feeds Ctrl (0x11) then V (0x56). All assertions kept (voice active, held key, approval blocked, release on device removal, stale release, no stray combos). |
| test_usb_uses_same_actions_and_ignores_releases_modifiers_and_stale_reports (found failing in the same file) | a | Approve/voice key codes changed (Tab, Ctrl+V). | test_hub.py: approve = 0x2B, voice = Ctrl+V; added "plain V (knob-3 press) is not voice"; stale/multi-key events built with `new_modifiers`. |
| test_usb_voice_release_cannot_be_lost_to_a_stale_timestamp, test_usb_unaccepted_press_has_no_release_action (same) | a | Voice key changed to Ctrl+V. | test_hub.py: events use ctrl+hid:0x19 with `modifiers`/`new_modifiers`. |

## test_hub_app_switch.py
| Test | Class | Root cause | Change |
|---|---|---|---|
| test_long_shared_control_feedback_wraps_and_keeps_header_buttons_visible | a | v9 removed the wrapping header label; feedback is a fixed 220x28 one-line toast in its own window. | Replaced with test_long_shared_control_feedback_is_clipped_to_one_fixed_line_toast: long control+action text is clipped to one line (<=29 columns, ends with an ellipsis), toast size is 220x28, strip bounds/geometry unchanged, no `feedback_label`. |
| test_usb_knob_reports_dispatch_window_and_name_both_directions | a | v9 knob 1 needs 2 pulses for the first step (threshold 2, rest resets), and successful window switches show no toast. | Each direction now sends 1 pulse (no dispatch) then 2nd pulse (dispatch next/prev, log names the knob); success leaves `last_input` empty; added a failed switch case that names "旋钮 1 顺时针 → 此操作不可用" (grey noop). |
| test_v6_untouched_upgrade_backup_and_idempotence (and test_v7_untouched..., found failing in the same file) | a | Old defaults are now v8 baseline (`app.V8_BINDINGS`) patched per version, target is v9, and any `layers` key counts as a user edit. | Helper `old_keymap()` builds the old default from `V8_BINDINGS`+`OLD_DEFAULTS` (no layers); shipped version asserted 9; backup/idempotence checks unchanged. The "custom ... stay byte identical" tests now start from the same real old default so they test real edits, not a trivially different baseline. |

## test_hub_desktop_mac.py
| Test | Class | Root cause | Change |
|---|---|---|---|
| test_hub_reports_unavailable_when_native_action_returns_false | b | `MacDesktopEffects.interrupt()` rejected the new `layer` keyword from `hub_controls`; also `hub_controls._desktop` mapped a `False` result to status "error" instead of macOS "unavailable". | hub_desktop_mac.py: `interrupt(..., layer=None)`. hub_controls.py: `False` on `sys.platform == "darwin"` returns `{"status": "unavailable"}` (other platforms unchanged: "error"). |
| test_missing_window_action_reports_focus_failure_once | b | v9 `DesktopEffects.interrupt` uses the current foreground window (Windows UIA Stop button / Esc) and never focuses the session first; on macOS this skipped `_focus` and logged "foreground changed" instead of the window-focus failure, and could press Esc in the wrong app. | hub_desktop_mac.py: `interrupt` override focuses the selected session window (`_focus`), then sends Esc (keycode 53), as before v9; Windows-only UIA path is not used on macOS. |

## test_hub_nonce_integration.py
| Test | Class | Root cause | Change |
|---|---|---|---|
| test_headless_hotkey_and_usb_approve_and_deny | a | The test used hid:0x09 as "deny"; that code is now knob-1 clockwise, which the detent filter swallows until the second pulse. | USB deny now uses v9 ctrl+hid:0x06 (Ctrl+C) with matching modifiers; same assertions (both requests resolved). |
| test_measured_idle_keys_decode_into_real_hub_effects_in_both_profiles | a | The default profile is v9 (M copy, Ctrl+T paste, U send, X clear, Tab approve, Ctrl+C deny, Q jump to waiting session, Ctrl+V voice); the `v2_emulation` profile is still the legacy v8-style opt-in profile and still passes unchanged. | Split in two: `..._in_default_v9_profile` (asserts the v9 effects above, idle approve/deny do nothing and write no audit, no `prompt` calls, Q jumps to the session with a native permission prompt, Ctrl+V gives voice_down/voice_up) and `..._in_v2_emulation_profile` (the original v8 assertions, unchanged). |

## Final per-file status
See the final message of the task (all `pc/test_*.py` run on their own).
