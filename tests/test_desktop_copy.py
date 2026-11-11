from pathlib import Path

PLUGIN_JS = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()


def test_settings_row_says_what_myfolks_connects_to():
    assert "storeRowBody: 'Encrypted in this Hermes profile. MyFolks itself connects to nothing.'," in PLUGIN_JS


def test_old_settings_wording_is_gone():
    assert "Nothing is sent anywhere." not in PLUGIN_JS


def test_card_opens_again_for_each_search_result():
    assert "  }, [answerCardId, data])\n" in PLUGIN_JS
    assert "  }, [answerCardId])\n" not in PLUGIN_JS
