from unittest.mock import patch

from jarvis import config
from jarvis.brain import Brain


def test_low_memory_profile_preserves_personal_settings_and_avoids_embedding(isolated_app):
    cfg, db, _, _ = isolated_app
    cfg['honorific'] = 'Brett'
    updated = config.apply_profile(cfg, 'low-memory')
    assert cfg['model'] == 'qwen3:8b'
    assert updated['honorific'] == 'Brett'
    config.save(updated)
    loaded = config.load()
    assert loaded['num_ctx'] == 2048
    brain = Brain(loaded, db)
    with patch.object(brain, '_post', return_value={'message': {'content': 'Ready'}}) as post:
        assert brain.embed('A remembered preference') is None
        post.assert_not_called()
        brain._chat([{'role': 'user', 'content': 'Hello'}], use_tools=False)
        payload = post.call_args.args[1]
        assert payload['keep_alive'] == 0
        assert payload['options']['num_ctx'] == 2048
    restored = config.apply_profile(loaded, 'standard')
    assert restored['memory_embeddings'] is True
    assert restored['honorific'] == 'Brett'
