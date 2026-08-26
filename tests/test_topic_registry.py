import opportunity_radar


def test_topic_registry_reuses_a_stable_id_after_reopening_storage(tmp_path) -> None:
    """Regenerating IDs for a known community topic breaks longitudinal trend comparisons."""
    path = tmp_path / "topic-registry.json"
    registry = opportunity_radar.TopicRegistry(path)

    first = registry.get_or_create(
        community="powerstroke",
        canonical_key="legal-dpf-replacement",
        label_en="Legal DPF replacement",
        label_zh="合规 DPF 替换件",
    )
    reopened = opportunity_radar.TopicRegistry(path)
    second = reopened.get_or_create(
        community="powerstroke",
        canonical_key="legal-dpf-replacement",
        label_en="Replacement DPF legality",
        label_zh="DPF 替换合规性",
    )

    assert first.topic_id == second.topic_id
    assert second.label_en == "Legal DPF replacement"
    assert reopened.records() == (first,)
