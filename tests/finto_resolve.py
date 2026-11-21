"""Resolve simulato per i test. Riproduce le trappole già incontrate sul Mac di Diego."""
from __future__ import annotations

import os
import itertools

_ids = itertools.count(1)


COMP_MINIMA = """Composition {
	RenderRange = { 0, 54 },
	Tools = {
		MediaIn1 = Loader {
			Inputs = {
				GlobalIn = Input { Value = -185, },
			},
		},
		MediaOut1 = Saver {
			Inputs = {
				Index = Input { Value = "0", },
				Input = Input {
					SourceOp = "MediaIn1",
					Source = "Output",
				}
			},
		}
	},
	Frames = {
	},
}
"""


class FintoMPI:
    def __init__(self, nome, path="/finto/", fps="25", res="2160x3840", gamma="S-Log3"):
        self.nome = nome
        self.props = {"File Path": path + nome, "FPS": fps, "Resolution": res, "Gamma Notes": gamma,
                      "Video Codec": "H.265"}

    def GetName(self):
        return self.nome

    def GetClipProperty(self, k=None):
        return dict(self.props) if k is None else self.props.get(k)


class FintoGrafo:
    def __init__(self, etichette):
        self.etichette = etichette

    def GetNumNodes(self): return len(self.etichette)
    def GetNodeLabel(self, n): return self.etichette[n - 1]
    def GetLUT(self, n): return ""
    def GetToolsInNode(self, n): return []


class FintoStrumento:
    def __init__(self, tipo, nome):
        self.tipo, self.nome, self.ingressi, self.chiavi, self.collegati = tipo, nome, {}, {}, {}

    def SetInput(self, k, v, frame=None):
        if frame is None:
            self.ingressi[k] = v
        else:
            self.chiavi.setdefault(k, []).append((frame, v))
        return True
    def AddModifier(self, k, tipo): return True
    def ConnectInput(self, k, altro): self.collegati[k] = altro; return True


class FintaComp:
    def __init__(self):
        self.strumenti = {"MediaIn1": FintoStrumento("MediaIn", "MediaIn1"), "MediaOut1": FintoStrumento("MediaOut", "MediaOut1")}
        self.strumenti["MediaOut1"].collegati["Input"] = self.strumenti["MediaIn1"]

    def AddTool(self, tipo):
        n = f"{tipo}{sum(1 for s in self.strumenti.values() if s.tipo == tipo) + 1}"
        self.strumenti[n] = FintoStrumento(tipo, n); return self.strumenti[n]
    def FindTool(self, n): return self.strumenti.get(n)
    def GetAttrs(self): return {"COMPN_RenderStart": 0}


class FintaCartella:
    def __init__(self, nome, clip=(), sotto=()):
        self.nome, self.clip, self.sotto = nome, list(clip), list(sotto)

    def GetName(self): return self.nome
    def GetClipList(self): return self.clip
    def GetSubFolderList(self): return self.sotto


class FintoItem:
    def __init__(self, nome, inizio, fine, offset, mpi=None):
        self.nome, self.inizio, self.fine, self.offset, self.mpi = nome, inizio, fine, offset, mpi
        self.id = str(next(_ids))
        self.comp = 0
        self.import_fatti = 0
        self.grafo = FintoGrafo(["CST S-Log3", "Bilanciamento"])
        self.gruppo = None
        self.comps = []

    def GetName(self): return self.nome
    def GetUniqueId(self): return self.id
    def GetStart(self): return self.inizio
    def GetEnd(self): return self.fine
    def GetDuration(self): return self.fine - self.inizio
    def GetLeftOffset(self): return self.offset
    def GetMediaPoolItem(self): return self.mpi
    def GetFusionCompCount(self): return max(self.comp, len(self.comps))
    def GetFusionCompByIndex(self, i): return self.comps[i - 1] if self.comps else FintaComp()
    def AddFusionComp(self):
        c = FintaComp(); self.comps.append(c); return c
    def GetNodeGraph(self): return self.grafo
    def GetColorGroup(self): return self.gruppo
    def AssignToColorGroup(self, g): self.gruppo = g; return True
    def SmartReframe(self): return True
    def ExportFusionComp(self, path, i):
        open(path, "w").write(COMP_MINIMA); return True
    def ImportFusionComp(self, path):
        self.import_fatti += 1; return True


class FintaTimeline:
    def __init__(self, nome, inizio=90000, fps="25"):
        self.nome, self.inizio, self.fps = nome, inizio, fps
        self.tracce = {"video": [[]], "audio": [[]], "subtitle": []}
        self.testina = None
        self.voce = {}

    def GetName(self): return self.nome
    def GetStartFrame(self): return self.inizio
    def GetEndFrame(self):
        fini = [i.fine for tr in self.tracce.values() for t in tr for i in t]
        return max(fini, default=self.inizio)
    def GetSetting(self, k): return self.fps if k == "timelineFrameRate" else None
    def GetTrackCount(self, tipo): return len(self.tracce[tipo])
    def GetItemListInTrack(self, tipo, n): return sorted(self.tracce[tipo][n - 1], key=lambda i: i.inizio)
    def DeleteClips(self, items, ripple):
        for tr in self.tracce.values():
            for t in tr:
                for i in items:
                    if i in t: t.remove(i)
        return True
    def DuplicateTimeline(self, nome):
        return self.progetto._aggiungi(FintaTimeline(nome, self.inizio, self.fps))
    def SetCurrentTimecode(self, tc):
        self.testina = tc; return True
    def SetVoiceIsolationState(self, tr, s):
        self.voce[tr] = s; return True
    def GetVoiceIsolationState(self, tr): return self.voce.get(tr)
    def AddMarker(self, *a):
        self.marker = getattr(self, "marker", []) + [a]; return True


class FintoMediaPool:
    def __init__(self, progetto, radice, record_assoluto=True, end_escluso=True):
        self.p, self.radice = progetto, radice
        self.record_assoluto, self.end_escluso = record_assoluto, end_escluso

    def GetRootFolder(self): return self.radice

    def CreateEmptyTimeline(self, nome):
        t = FintaTimeline(nome, 90000, "25")
        self.p._aggiungi(t)
        return t

    def AppendToTimeline(self, infos):
        t = self.p.GetCurrentTimeline()
        out = []
        for info in infos:
            rec = info["recordFrame"] if self.record_assoluto else t.inizio + info["recordFrame"]
            durata = info["endFrame"] - info["startFrame"] + (0 if self.end_escluso else 1)
            tipi = {1: ["video"], 2: ["audio"]}.get(info.get("mediaType"), ["video", "audio"])
            for tipo in tipi:
                it = FintoItem(info["mediaPoolItem"].GetName(), rec, rec + durata, info["startFrame"], info["mediaPoolItem"])
                tr = t.tracce[tipo]
                while len(tr) < info["trackIndex"]:
                    tr.append([])
                tr[info["trackIndex"] - 1].append(it)
                out.append(it)
        return out


class FintoProgetto:
    def __init__(self, **kw):
        self.timeline = []
        self.corrente = None
        self.radice = FintaCartella("Master", [FintoMPI("C6594.MP4"), FintoMPI("Musica.wav")],
                                    [FintaCartella("B-ROLL", [FintoMPI("C7001.MP4")])])
        self.mp = FintoMediaPool(self, self.radice, **kw)
        self.jobs = []
        self.render_impostazioni = {}
        self.resolve = None
        self.avvii = 0

    def _aggiungi(self, t):
        t.progetto = self
        self.timeline.append(t)
        if self.corrente is None:
            self.corrente = t
        return t

    def GetName(self): return "REEL 016 Prato Pescheria"
    def GetSetting(self, k=None):
        d = {"timelineFrameRate": "25", "colorScienceMode": "davinciYRGBColorManagedv2"}
        return d if k is None else d.get(k)
    def GetColorGroupsList(self): return getattr(self, "gruppi", [])
    def AddColorGroup(self, nome):
        g = type("G", (), {"GetName": lambda s, n=nome: n})()
        self.gruppi = self.GetColorGroupsList() + [g]; return g
    def GetCurrentTimeline(self): return self.corrente
    def SetCurrentTimeline(self, t): self.corrente = t; return True
    def GetTimelineCount(self): return len(self.timeline)
    def GetTimelineByIndex(self, i): return self.timeline[i - 1]
    def GetMediaPool(self): return self.mp
    def ExportCurrentFrameAsStill(self, path):
        open(path, "w").write("png"); return True
    def DeleteAllRenderJobs(self): self.jobs.clear(); return True
    def LoadRenderPreset(self, p): return p == "H.264 Master"
    def SetCurrentRenderFormatAndCodec(self, f, c): return True
    def SetRenderSettings(self, s):
        if s.get("VideoQuality") == "Best":
            return False
        self.render_impostazioni.update(s); return True
    def AddRenderJob(self):
        j = f"job{len(self.jobs) + 1}"; self.jobs.append(j); return j
    def StartRendering(self, jobs):
        # trappola del 17 nov: non parte se non si è in pagina Edit o con job vecchi in coda
        self.avvii += 1
        if self.resolve.pagina != "edit" or len(self.jobs) > 1:
            return False
        s = self.render_impostazioni
        os.makedirs(s["TargetDir"], exist_ok=True)
        open(os.path.join(s["TargetDir"], s["CustomName"] + ".mp4"), "wb").write(b"x" * 100)
        return True
    def IsRenderingInProgress(self): return False
    def GetRenderJobStatus(self, j): return {"JobStatus": "Complete", "CompletionPercentage": 100}


class FintoPM:
    def __init__(self, p): self.p = p
    def GetCurrentProject(self): return self.p


class FintoResolve:
    def __init__(self, **kw):
        self.p = FintoProgetto(**kw)
        self.p.resolve = self
        self.pagina = "color"

    def GetProjectManager(self): return FintoPM(self.p)
    def GetCurrentPage(self): return self.pagina
    def OpenPage(self, p): self.pagina = p; return True
