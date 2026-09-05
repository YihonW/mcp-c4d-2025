from __future__ import annotations

import types

RS_RENDERER_ID = 1036219
RS_POST_EFFECT_ID = 1040189


class FakeDocument:
    def __init__(self, name: str):
        self.name = name
        self.next: FakeDocument | None = None

    def GetDocumentName(self):
        return self.name

    def GetNext(self):
        return self.next


class FakeDocuments:
    def __init__(self, names: list[str]):
        self.items = [FakeDocument(name) for name in names]
        for current, following in zip(self.items, self.items[1:], strict=False):
            current.next = following
        self.active = self.items[0] if self.items else None
        self.active_changes: list[FakeDocument | None] = []
        self.event_add_calls = 0

    def GetFirstDocument(self):
        return self.items[0] if self.items else None

    def GetActiveDocument(self):
        return self.active

    def SetActiveDocument(self, document):
        self.active = document
        self.active_changes.append(document)


class FakePlugin:
    def __init__(self, plugin_id: int):
        self.plugin_id = plugin_id


class FakePluginLookup:
    def __init__(self, available: set[int]):
        self.available = available
        self.calls: list[tuple[int, object]] = []

    def FindPlugin(self, plugin_id, plugin_type):
        self.calls.append((plugin_id, plugin_type))
        return FakePlugin(plugin_id) if plugin_id in self.available else None


class FakeId:
    def __init__(self, value=""):
        self.value = str(value)

    def __str__(self):
        return self.value


class FakeNodeTemplate:
    def __init__(self, asset_id: str):
        self.asset_id = asset_id

    def GetId(self):
        return FakeId(self.asset_id)


class FakeNodeTemplateRepository:
    def __init__(self, asset_ids: tuple[str, ...]):
        self.assets = [FakeNodeTemplate(asset_id) for asset_id in asset_ids]
        self.calls: list[tuple[object, ...]] = []

    def FindAssets(self, *args):
        if not args or not isinstance(args[0], FakeId):
            raise TypeError("assetType expects Id, not the NodeTemplate declaration")
        self.calls.append(args)
        return self.assets

    def FindLatestAsset(self, _asset_type, asset_id):
        wanted = str(asset_id)
        return next((asset for asset in self.assets if asset.asset_id == wanted), None)


def make_c4d_runtime(
    *,
    document_names: list[str] | None = None,
    plugins: set[int] | None = None,
    light_types: set[str] | None = None,
):
    document_state = FakeDocuments(document_names or ["scene"])
    plugin_lookup = FakePluginLookup(plugins or {RS_RENDERER_ID, RS_POST_EFFECT_ID})
    c4d = types.ModuleType("c4d")
    documents = types.ModuleType("c4d.documents")
    documents.GetFirstDocument = document_state.GetFirstDocument
    documents.GetActiveDocument = document_state.GetActiveDocument
    documents.SetActiveDocument = document_state.SetActiveDocument
    c4d.documents = documents
    c4d.plugins = plugin_lookup
    c4d.GetC4DVersion = lambda: 2025302

    def event_add():
        document_state.event_add_calls += 1

    c4d.EventAdd = event_add
    c4d.PLUGINTYPE_VIDEOPOST = 1
    c4d.Orslight = 1036751
    c4d.Orscamera = 1057516
    c4d.REDSHIFT_LIGHT_TYPE = 10000
    symbols = {
        "area": "REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA",
        "dome": "REDSHIFT_LIGHT_TYPE_DOME",
        "sun": "REDSHIFT_LIGHT_TYPE_PHYSICALSUN",
        "point": "REDSHIFT_LIGHT_TYPE_PHYSICAL_POINT",
        "spot": "REDSHIFT_LIGHT_TYPE_PHYSICAL_SPOT",
    }
    for index, light_type in enumerate(light_types or {"area", "dome", "sun", "point", "spot"}, 1):
        setattr(c4d, symbols[light_type], index)
    return c4d, documents, document_state, plugin_lookup


def make_maxon_runtime(asset_ids: tuple[str, ...]):
    repository = FakeNodeTemplateRepository(asset_ids)
    maxon = types.ModuleType("maxon")
    maxon.Id = FakeId
    maxon.AssetTypes = types.SimpleNamespace(
        NodeTemplate=lambda: types.SimpleNamespace(GetId=lambda: FakeId("node-template"))
    )
    maxon.AssetInterface = types.SimpleNamespace(GetUserPrefsRepository=lambda: repository)
    return maxon, repository


def make_redshift_runtime():
    redshift = types.ModuleType("redshift")
    redshift.FindAddVideoPost = lambda *_args: None
    redshift.RendererGetAOVs = lambda *_args: []
    redshift.RendererSetAOVs = lambda *_args: None
    redshift.RSAOV = type("RSAOV", (), {})
    redshift.VPrsrenderer = 1036219
    return redshift
