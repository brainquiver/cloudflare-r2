"""Dataset mode: the tool sends a dataset directory as its card and its curated tree.

The keys start with the name of the directory. The inner folder takes a name that the caller
gives, or --flat removes it. The config directories inside it always stay. Two configs hold
shards with the same names.
"""
import sys

import pytest

import push
from fake_service import Reply, error, listing

SHARD = "train-00000-of-00001.parquet"


@pytest.fixture
def dataset(tmp_path):
    d = tmp_path / "geo"
    (d / "curated" / "cfg_a").mkdir(parents=True)
    (d / "curated" / "cfg_b").mkdir(parents=True)
    (d / "samples").mkdir()
    (d / "geo_card.md").write_text("card")
    (d / "curated" / "cfg_a" / SHARD).write_bytes(b"a")
    (d / "curated" / "cfg_b" / SHARD).write_bytes(b"bb")
    (d / "curated" / ".DS_Store").write_bytes(b"x")
    (d / "curated" / "cfg_a" / "._train").write_bytes(b"x")
    (d / "samples" / "raw.jsonl").write_text("{}")
    return d


def keys(pairs):
    return sorted(k for k, _ in pairs)


def test_the_inner_folder_keeps_its_given_name(dataset):
    assert keys(push.dataset_files(dataset, inner="curated")) == [
        f"geo/curated/cfg_a/{SHARD}", f"geo/curated/cfg_b/{SHARD}", "geo/geo_card.md"]


def test_another_inner_name_replaces_curated(dataset):
    assert keys(push.dataset_files(dataset, inner="shards")) == [
        "geo/geo_card.md", f"geo/shards/cfg_a/{SHARD}", f"geo/shards/cfg_b/{SHARD}"]


def test_flat_drops_the_inner_folder_and_keeps_the_config_folders(dataset):
    assert keys(push.dataset_files(dataset, inner=None)) == [
        f"geo/cfg_a/{SHARD}", f"geo/cfg_b/{SHARD}", "geo/geo_card.md"]


def test_macos_metadata_and_other_folders_stay_out(dataset):
    found = keys(push.dataset_files(dataset, inner="curated"))
    assert not any(".DS_Store" in k or "/._" in k or "samples" in k for k in found)


def test_a_dataset_without_its_card_is_refused(dataset):
    (dataset / "geo_card.md").unlink()
    with pytest.raises(RuntimeError, match="geo_card.md"):
        push.dataset_files(dataset, inner="curated")


def test_two_datasets_with_one_name_are_refused(tmp_path, dataset):
    other = tmp_path / "elsewhere" / "geo"
    (other / "curated").mkdir(parents=True)
    (other / "geo_card.md").write_text("card")
    (other / "curated" / SHARD).write_bytes(b"c")
    with pytest.raises(RuntimeError, match="geo"):
        push.collect_datasets([dataset, other], inner="curated")


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["push.py", *args])
    push.main()


def test_the_cli_needs_an_explicit_layout(credentials, dataset, monkeypatch, capsys):
    with pytest.raises(SystemExit) as stop:
        run(monkeypatch, "datasets", "--dataset", str(dataset))
    assert stop.value.code != 0
    assert "--inner NAME or --flat" in capsys.readouterr().err


def test_the_cli_sends_the_card_and_shards_under_the_dataset_folder(
        transport, credentials, dataset, monkeypatch):
    transport.on("PUT", "/datasets", error(409, "BucketAlreadyOwnedByYou"))
    transport.on("GET", "/datasets", listing([]), query={"list-type"})
    for key in ("geo/geo_card.md", f"geo/curated/cfg_a/{SHARD}", f"geo/curated/cfg_b/{SHARD}"):
        transport.on("PUT", f"/datasets/{key}", Reply(200))
    run(monkeypatch, "datasets", "--dataset", str(dataset), "--inner", "curated")
    sent = {c.path: c.body for c in transport.calls if c.method == "PUT" and c.path != "/datasets"}
    assert sent == {"/datasets/geo/geo_card.md": b"card",
                    f"/datasets/geo/curated/cfg_a/{SHARD}": b"a",
                    f"/datasets/geo/curated/cfg_b/{SHARD}": b"bb"}


def test_a_prefix_sits_above_the_dataset_folder(transport, credentials, dataset, monkeypatch):
    transport.on("PUT", "/datasets", error(409, "BucketAlreadyOwnedByYou"))
    transport.on("GET", "/datasets", listing([]), query={"list-type"})
    for key in ("geo/geo_card.md", f"geo/cfg_a/{SHARD}", f"geo/cfg_b/{SHARD}"):
        transport.on("PUT", f"/datasets/archive/{key}", Reply(200))
    run(monkeypatch, "datasets", "--dataset", str(dataset), "--flat", "--prefix", "archive")
    sent = sorted(c.path for c in transport.calls if c.method == "PUT" and c.path != "/datasets")
    assert sent == ["/datasets/archive/geo/cfg_a/" + SHARD, "/datasets/archive/geo/cfg_b/" + SHARD,
                    "/datasets/archive/geo/geo_card.md"]
