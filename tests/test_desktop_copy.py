from pathlib import Path

PLUGIN_JS = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()


def test_settings_row_says_what_myfolks_connects_to():
    assert "storeRowBody: 'Encrypted in this Hermes profile. MyFolks connects only to Google, and only after you send /myfolks sync.'," in PLUGIN_JS
    assert "connects to nothing" not in PLUGIN_JS
    assert "recoveryRow: 'If MyFolks stops opening'," in PLUGIN_JS
    assert "recoveryRowBody: 'Unlock it with your recovery code: hermes myfolks recover'," in PLUGIN_JS
    assert "New device" not in PLUGIN_JS


def test_old_settings_wording_is_gone():
    assert "Nothing is sent anywhere." not in PLUGIN_JS


def test_card_opens_again_for_each_search_result():
    assert "  }, [answerCardId, data])\n" in PLUGIN_JS
    assert "  }, [answerCardId])\n" not in PLUGIN_JS


def test_setup_screen_wording():
    assert "setupCodeIntro: 'Your recovery code. It is shown once. Keep it somewhere safe:'," in PLUGIN_JS
    assert "setupCodeNeeded" not in PLUGIN_JS
    assert "body = jsx(SetupPanel, { ctx, onDone: status.reload })" in PLUGIN_JS


def test_setup_screen_points_to_sync_right_after_ready():
    assert "setupNext: 'Next, bring in your contacts: send /myfolks sync to use your Google contacts, or run hermes myfolks import <file>.'," in PLUGIN_JS
    assert "jsx(Note, { children: COPY.setupDone }), jsx(Note, { children: COPY.setupNext })" in PLUGIN_JS
