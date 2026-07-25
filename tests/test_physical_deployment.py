import json
from pathlib import Path

import pytest
import yaml

from rarelink.deployment.topology import (
    PhysicalTopology,
    load_physical_topology,
    render_nvflare_project,
    topology_sha256,
)
from scripts.nvflare_monai_client import validate_manifest_for_site
from scripts.render_physical_federation import write_rendered_contract
from scripts.validate_physical_site import local_manifest_summary


def topology_payload() -> dict:
    return {
        "schema_version": "rarelink-physical-topology-v1",
        "federation_name": "rarelink-pilot",
        "coordinator": {
            "endpoint": {
                "hostname": "flare-coordinator.research.example.org",
                "fed_learn_port": 8002,
                "admin_port": 8003,
            },
            "organization": "rarelink_coordinator",
            "admin_identity": "admin@rarelink.example.org",
        },
        "sites": [
            {"site_id": "hospital-a", "organization": "hospital_a", "spark_label": "A"},
            {"site_id": "hospital-b", "organization": "hospital_b", "spark_label": "B"},
            {"site_id": "hospital-c", "organization": "hospital_c", "spark_label": "C"},
        ],
    }


def test_physical_topology_renders_real_server_and_three_clients() -> None:
    topology = PhysicalTopology.model_validate(topology_payload())
    project = render_nvflare_project(topology)

    assert project["participants"][0]["name"] == "flare-coordinator.research.example.org"
    assert [item["name"] for item in project["participants"] if item["type"] == "client"] == [
        "hospital-a",
        "hospital-b",
        "hospital-c",
    ]
    assert topology.public_contract()["raw_patient_data_in_topology"] is False
    assert len(topology_sha256(topology)) == 64


def test_physical_topology_rejects_localhost_and_reused_organization() -> None:
    invalid_host = topology_payload()
    invalid_host["coordinator"]["endpoint"]["hostname"] = "localhost"
    with pytest.raises(ValueError, match="routable FQDN"):
        PhysicalTopology.model_validate(invalid_host)

    invalid_org = topology_payload()
    invalid_org["sites"][2]["organization"] = "hospital_a"
    with pytest.raises(ValueError, match="independent organization"):
        PhysicalTopology.model_validate(invalid_org)


def test_rendered_physical_source_contains_no_sensitive_paths(tmp_path: Path) -> None:
    topology_path = tmp_path / "topology.yml"
    topology_path.write_text(yaml.safe_dump(topology_payload()), encoding="utf-8")

    receipt = write_rendered_contract(topology_path, tmp_path / "rendered")
    rendered = (tmp_path / "rendered" / "project.yml").read_text(encoding="utf-8")

    assert receipt["contains_patient_data"] is False
    assert receipt["contains_private_keys"] is False
    assert "/srv/" not in rendered
    assert "client.key" not in rendered
    assert load_physical_topology(topology_path).federation_name == "rarelink-pilot"


def test_local_manifest_summary_rejects_foreign_site_cases(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {"site_id": "hospital-a", "images": ["image-a.nii.gz"], "label": "a.nii.gz"},
                    {"site_id": "hospital-a", "images": ["image-b.nii.gz"], "label": "b.nii.gz"},
                ]
            }
        ),
        encoding="utf-8",
    )
    summary = local_manifest_summary(manifest, "hospital-a")
    assert summary["local_case_count"] == 2
    assert summary["case_identifiers_exported"] is False

    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {"site_id": "hospital-a", "images": ["image-a.nii.gz"], "label": "a.nii.gz"},
                    {"site_id": "hospital-b", "images": ["image-b.nii.gz"], "label": "b.nii.gz"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only the local site's cases"):
        local_manifest_summary(manifest, "hospital-a")


def test_physical_monai_client_rejects_foreign_cases_before_loading_images(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {"site_id": "hospital-a", "images": ["a1.nii.gz"], "label": "a1.nii.gz"},
                    {"site_id": "hospital-a", "images": ["a2.nii.gz"], "label": "a2.nii.gz"},
                    {"site_id": "hospital-b", "images": ["b1.nii.gz"], "label": "b1.nii.gz"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert len(validate_manifest_for_site(manifest, "hospital-a")["cases"]) == 3
    with pytest.raises(ValueError, match="non-local cases"):
        validate_manifest_for_site(manifest, "hospital-a", require_local_only=True)
