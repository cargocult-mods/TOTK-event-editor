import types
import unittest
from pathlib import Path


from eventeditor.actor_safety_params import (
    ACTOR_SAFETY_PARAM_DEFAULTS,
    actor_safety_findings_text,
    collect_actor_safety_param_findings,
    ensure_actor_safety_params,
    repair_actor_safety_params,
)


class FakeContainer:
    def __init__(self, data=None):
        self.data = dict(data or {})


def make_actor(name, params):
    return types.SimpleNamespace(
        identifier=types.SimpleNamespace(name=name, sub_name=''),
        params=params,
    )


def make_flow(*actors, events=()):
    flowchart = types.SimpleNamespace(name='TestFlow', actors=list(actors), events=list(events))
    return types.SimpleNamespace(flowchart=flowchart)


class ActorSafetyParamTests(unittest.TestCase):
    def test_new_actor_receives_the_complete_conservative_baseline(self):
        actor = make_actor('NewActor', None)

        changed = ensure_actor_safety_params(actor, FakeContainer)

        self.assertTrue(changed)
        self.assertEqual(actor.params.data, ACTOR_SAFETY_PARAM_DEFAULTS)

    def test_collects_no_params_separately_from_missing_baseline_params(self):
        empty = make_actor('EmptyActor', None)
        partial = make_actor('PartialActor', FakeContainer({'IsWorld': True}))
        complete = make_actor('CompleteActor', FakeContainer(ACTOR_SAFETY_PARAM_DEFAULTS))

        findings = collect_actor_safety_param_findings(make_flow(empty, partial, complete))

        self.assertEqual([finding.actor_name for finding in findings.no_params], ['EmptyActor'])
        self.assertEqual([finding.actor_name for finding in findings.missing_some], ['PartialActor'])
        self.assertEqual(
            findings.missing_some[0].missing_keys,
            tuple(key for key in ACTOR_SAFETY_PARAM_DEFAULTS if key != 'IsWorld'),
        )

    def test_unused_placeholder_actor_does_not_need_safety_parameters(self):
        placeholder = make_actor('<placeholder actor>', None)

        findings = collect_actor_safety_param_findings(make_flow(placeholder))

        self.assertEqual(findings.no_params, [])
        self.assertEqual(findings.missing_some, [])

    def test_referenced_placeholder_actor_still_needs_safety_parameters(self):
        placeholder = make_actor('<placeholder actor>', None)
        event = types.SimpleNamespace(
            data=types.SimpleNamespace(actor=types.SimpleNamespace(v=placeholder)),
        )

        findings = collect_actor_safety_param_findings(
            make_flow(placeholder, events=[event])
        )

        self.assertEqual(
            [finding.actor_name for finding in findings.no_params],
            ['<placeholder actor>'],
        )

    def test_repair_adds_only_missing_baseline_params_and_preserves_values(self):
        empty = make_actor('EmptyActor', None)
        partial = make_actor(
            'PartialActor',
            FakeContainer({'IsWorld': True, 'CustomParam': 7}),
        )
        findings = collect_actor_safety_param_findings(make_flow(empty, partial))

        repaired = repair_actor_safety_params(
            findings.no_params + findings.missing_some,
            FakeContainer,
        )

        self.assertEqual(repaired, 2)
        self.assertEqual(empty.params.data, ACTOR_SAFETY_PARAM_DEFAULTS)
        self.assertTrue(partial.params.data['IsWorld'])
        self.assertEqual(partial.params.data['CustomParam'], 7)
        for key, value in ACTOR_SAFETY_PARAM_DEFAULTS.items():
            if key != 'IsWorld':
                self.assertEqual(partial.params.data[key], value)

    def test_warning_details_name_actors_and_missing_fields(self):
        actor = make_actor('PartialActor', FakeContainer({'IsWorld': False}))
        finding = collect_actor_safety_param_findings(make_flow(actor)).missing_some[0]

        text = actor_safety_findings_text([finding], include_missing_keys=True)

        self.assertIn('TestFlow / PartialActor', text)
        self.assertIn('EventMemberCreateMethod', text)
        self.assertNotIn('IsWorld,', text)

    def test_creation_and_save_checks_use_the_shared_safety_baseline(self):
        source_root = Path(__file__).resolve().parents[1] / 'eventeditor'
        actor_model_source = (source_root / 'actor_model.py').read_text(encoding='utf-8')
        event_chooser_source = (source_root / 'event_chooser_dialog.py').read_text(encoding='utf-8')
        main_source = (source_root / '__main__.py').read_text(encoding='utf-8')

        self.assertIn('ensure_actor_safety_params(actor, Container)', actor_model_source)
        self.assertIn('ensure_actor_safety_params(actor, Container)', event_chooser_source)
        self.assertIn('def confirmActorSafetyParametersForSave', main_source)
        self.assertIn('Actors have no parameters', main_source)
        self.assertIn('Actors may be missing safety parameters', main_source)
        self.assertIn('Add missing parameters', main_source)
        self.assertIn('self.confirmActorSafetyParametersForSave()', main_source)


if __name__ == '__main__':
    unittest.main()
