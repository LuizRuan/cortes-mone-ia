import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { motion, MotionConfig } from "motion/react";
import { sha256 } from "@noble/hashes/sha256";
import {
  ArrowDown,
  ArrowRight,
  Check,
  ChevronDown,
  Film,
  LoaderCircle,
  Moon,
  Pause,
  Play,
  Plus,
  Scissors,
  Settings2,
  Sparkles,
  Sun,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import "./style.css";

type Clip = {
  id: string;
  title: string;
  rationale: string;
  duration: number;
  preview_status: string;
  original_status: string;
  original_progress?: number;
  original_error?: string;
};
type Params = { count: number; min_seconds: number; max_seconds: number };
type Health = { ai_configured: boolean; ai_provider: "local" | "groq" };
type Project = {
  id: string;
  name: string;
  size: number;
  fingerprint: string;
  offset: number;
  status: string;
  stage: string;
  progress: number;
  elapsed_seconds?: number;
  units_done?: number;
  units_total?: number;
  previews_ready?: number;
  clips: Clip[];
  error?: string;
  notice?: string;
  params?: Params;
};
const CHUNK = 8 * 1024 * 1024,
  MAX = 20_000_000_000;
const remembered = () => {
  try {
    return JSON.parse(localStorage.getItem("cortes-projects") || "[]") as {
      id: string;
      name: string;
    }[];
  } catch {
    return [];
  }
};
const savedTheme = () => {
  try {
    return localStorage.getItem("cortes-theme") || "dark";
  } catch {
    return "dark";
  }
};
function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private browser */
  }
}
function remember(p: Project) {
  const url = new URL(location.href);
  url.searchParams.set("project", p.id);
  window.history.replaceState(null, "", url);
  save("cortes-current", p.id);
  save(
    "cortes-projects",
    JSON.stringify([
      { id: p.id, name: p.name },
      ...remembered().filter((x) => x.id !== p.id),
    ]),
  );
}
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch("/api" + path, options);
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "Não foi possível conectar ao servidor." }));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Confira as opções e tente novamente.",
    );
  }
  return response.json();
}
const post = <T,>(path: string, body: unknown = {}) =>
  api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
async function hash(blob: Blob) {
  return Array.from(sha256(new Uint8Array(await blob.arrayBuffer())))
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}
async function fingerprint(f: File) {
  return hash(
    new Blob([
      f.slice(0, 1024 * 1024),
      f.slice(Math.max(0, f.size - 1024 * 1024)),
      `${f.name}|${f.size}|${f.lastModified}`,
    ]),
  );
}
const size = (bytes: number) =>
  bytes >= 1e9
    ? `${(bytes / 1e9).toFixed(1)} GB`
    : `${(bytes / 1e6).toFixed(1)} MB`;
const duration = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

function App() {
  const [theme, setTheme] = useState(savedTheme),
    [project, setProject] = useState<Project | null>(null),
    [file, setFile] = useState<File | null>(null);
  const [params, setParams] = useState<Params>({
    count: 5,
    min_seconds: 30,
    max_seconds: 90,
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [drag, setDrag] = useState(false),
    [options, setOptions] = useState(false),
    [history, setHistory] = useState(false),
    [deleting, setDeleting] = useState(false);
  const [ai, setAi] = useState<Health | null>(null),
    [uploadProgress, setUploadProgress] = useState(0);
  const input = useRef<HTMLInputElement>(null),
    paused = useRef(false),
    abort = useRef<AbortController | null>(null);
  const projectRef = useRef<Project | null>(null);
  projectRef.current = project;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    save("cortes-theme", theme);
  }, [theme]);
  useEffect(() => {
    api<Health>("/health")
      .then(setAi)
      .catch(() => setError("Não foi possível conectar ao servidor."));
    const id =
      new URLSearchParams(location.search).get("project") ||
      localStorage.getItem("cortes-current");
    if (id)
      api<Project>("/projects/" + id)
        .then((p) => {
          setProject(p);
          remember(p);
          if (p.params) setParams(p.params);
        })
        .catch(() => save("cortes-current", ""));
    return () => abort.current?.abort();
  }, []);
  useEffect(() => {
    if (!project?.id) return;
    let active = true;
    const timer = setInterval(() => {
      if (busy) return;
      api<Project>("/projects/" + project.id)
        .then((p) => {
          if (active) setProject(p);
        })
        .catch(() => {});
    }, 1200);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [project?.id, busy]);
  function choose(f: File | undefined) {
    if (!f) return;
    if (f.size > MAX || f.size === 0) {
      setError("Selecione um vídeo de até 20 GB.");
      return;
    }
    if (!/\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(f.name)) {
      setError("Selecione um arquivo de vídeo.");
      return;
    }
    setFile(f);
    setError("");
  }
  async function create() {
    if (!file) return;
    setBusy(true);
    setError("");
    paused.current = false;
    try {
      const fp = await fingerprint(file);
      let p = projectRef.current;
      if (!p || p.status !== "uploading" || p.fingerprint !== fp) {
        p = await post<Project>("/projects", {
          name: file.name,
          size: file.size,
          fingerprint: fp,
        });
        remember(p);
        setProject(p);
      } else p = await api<Project>("/projects/" + p.id);
      const key = p.id;
      let offset = p.offset;
      setUploadProgress(offset / file.size);
      while (offset < file.size) {
        if (paused.current)
          throw new Error("Envio pausado. Clique em continuar para retomar.");
        const chunk = file.slice(offset, offset + CHUNK),
          digest = await hash(chunk);
        let delivered = false;
        for (let attempt = 0; attempt < 3 && !delivered; attempt++) {
          abort.current = new AbortController();
          try {
            p = await api<Project>(`/projects/${key}/upload?offset=${offset}`, {
              method: "PUT",
              headers: { "X-Chunk-SHA256": digest },
              body: chunk,
              signal: abort.current.signal,
            });
            offset = p.offset;
            delivered = true;
          } catch (e) {
            if (paused.current)
              throw new Error("Envio pausado. Você pode continuar depois.");
            const latest = await api<Project>("/projects/" + key);
            if (latest.offset > offset) {
              offset = latest.offset;
              delivered = true;
              p = latest;
            } else if (attempt === 2) throw e;
          }
        }
        setUploadProgress(offset / file.size);
        setProject(p);
      }
      p = await post<Project>(`/projects/${key}/complete`);
      setProject(p);
      p = await post<Project>(`/projects/${key}/start`, params);
      setProject(p);
      setFile(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }
  async function action(path: string, body: unknown = {}) {
    setError("");
    try {
      setProject(await post<Project>(`/projects/${project!.id}/${path}`, body));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function exportClip(c: Clip) {
    try {
      await post(`/projects/${project!.id}/clips/${c.id}/export`);
      setProject(await api<Project>("/projects/" + project!.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function fresh() {
    window.history.replaceState(null, "", location.pathname);
    setProject(null);
    setFile(null);
    setError("");
    save("cortes-current", "");
    setHistory(false);
    setUploadProgress(0);
  }
  async function remove() {
    try {
      await api(`/projects/${project!.id}`, { method: "DELETE" });
      save(
        "cortes-projects",
        JSON.stringify(remembered().filter((x) => x.id !== project!.id)),
      );
      fresh();
      setDeleting(false);
    } catch (e) {
      setError((e as Error).message);
      setDeleting(false);
    }
  }
  const processing =
    project &&
    ["queued", "processing", "cancelling", "validating"].includes(
      project.status,
    );
  const uploading = busy || project?.status === "uploading";
  const exporting = project?.clips.some((c) =>
    ["queued", "rendering"].includes(c.original_status),
  );
  const hasResults = !!project?.clips.length;
  const initial = !project || project.status === "uploading";
  const readyCount =
    project?.clips.filter((c) => c.preview_status === "ready").length || 0;
  const stage = project?.stage || "";
  const stages = [
    "Preparando vídeo",
    "Transcrevendo",
    "Montando histórias",
    "Preparando prévias",
  ];
  const stageIndex = stages.findIndex((s) => stage.startsWith(s));
  return (
    <MotionConfig reducedMotion="user">
      <div className="app-shell">
        <header>
          <a
            className="brand"
            href="#"
            onClick={(e) => {
              e.preventDefault();
              if (!busy) fresh();
            }}
          >
            <span className="brand-icon">
              <Scissors size={20} />
            </span>
            cortes<span className="brand-studio">studio</span>
          </a>
          <nav>
            <div className="history-wrap">
              <button
                className="text-button"
                onClick={() => setHistory(!history)}
              >
                Meus vídeos
                <ChevronDown size={14} />
              </button>
              {history && (
                <div className="history-menu">
                  {remembered().length === 0 ? (
                    <p>Seus vídeos aparecerão aqui.</p>
                  ) : (
                    remembered().map((p) => (
                      <button
                        disabled={busy}
                        key={p.id}
                        onClick={async () => {
                          try {
                            const next = await api<Project>(
                              "/projects/" + p.id,
                            );
                            setProject(next);
                            remember(next);
                            setParams(
                              next.params || {
                                count: 5,
                                min_seconds: 30,
                                max_seconds: 90,
                              },
                            );
                            setFile(null);
                            setError("");
                            setHistory(false);
                          } catch (e) {
                            setError((e as Error).message);
                          }
                        }}
                      >
                        <Film size={15} />
                        <span>{p.name}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
            <button
              className="icon-button"
              aria-label={
                theme === "dark" ? "Ativar modo claro" : "Ativar modo escuro"
              }
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </nav>
        </header>
        <main>
          {error && (
            <div role="alert" className="alert">
              <span>{error}</span>
              <button aria-label="Fechar aviso" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {initial ? (
            <motion.section
              className="upload-screen"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <div className="eyebrow">
                <span /> MENOS EDIÇÃO. MAIS HISTÓRIA.
              </div>
              <h1>
                Seu vídeo tem boas histórias.
                <br />
                <span>Vamos encontrar elas.</span>
              </h1>
              <p className="intro">
                Transforme gravações longas em cortes que fazem sentido.
                <br /> Assista às prévias. Baixe em alta qualidade só o que
                gostar.
              </p>
              <div className="upload-card">
                <input
                  ref={input}
                  type="file"
                  accept=".mp4,.mov,.mkv,.avi,.webm,.m4v"
                  hidden
                  onChange={(e) => choose(e.target.files?.[0])}
                />
                <button
                  className={`dropzone ${drag ? "dragging" : ""}`}
                  disabled={busy}
                  onClick={() => input.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDrag(true);
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDrag(false);
                    if (!busy) choose(e.dataTransfer.files[0]);
                  }}
                >
                  <span className="upload-icon">
                    {file ? <Film size={30} /> : <UploadCloud size={30} />}
                  </span>
                  <strong>
                    {file ? file.name : "Arraste seu vídeo para cá"}
                  </strong>
                  <span>
                    {file
                      ? `${size(file.size)} · clique para trocar`
                      : "ou clique para escolher um arquivo"}
                  </span>
                  <small>MP4, MOV, MKV e outros · até 20 GB</small>
                </button>
                {project?.status === "uploading" && !file && (
                  <p className="resume-note">
                    Envio pendente: <b>{project.name}</b>. Selecione o mesmo
                    arquivo para retomar de {size(project.offset)}.
                  </p>
                )}
                <div className="controls">
                  <div>
                    <label htmlFor="count">Quantos cortes?</label>
                    <div className="stepper">
                      <button
                        disabled={busy || params.count === 1}
                        aria-label="Menos cortes"
                        onClick={() =>
                          setParams({ ...params, count: params.count - 1 })
                        }
                      >
                        −
                      </button>
                      <input
                        id="count"
                        disabled={busy}
                        type="number"
                        min={1}
                        max={20}
                        value={params.count}
                        onChange={(e) =>
                          setParams({
                            ...params,
                            count: Math.max(
                              1,
                              Math.min(20, Number(e.target.value) || 1),
                            ),
                          })
                        }
                      />
                      <button
                        disabled={busy || params.count === 20}
                        aria-label="Mais cortes"
                        onClick={() =>
                          setParams({ ...params, count: params.count + 1 })
                        }
                      >
                        +
                      </button>
                    </div>
                  </div>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => setOptions(!options)}
                  >
                    <Settings2 size={15} />
                    {params.min_seconds}–{params.max_seconds}s
                    <ChevronDown size={14} />
                  </button>
                </div>
                {options && (
                  <div className="duration-options">
                    <label>
                      Mínimo (s)
                      <input
                        type="number"
                        min={5}
                        max={180}
                        value={params.min_seconds}
                        disabled={busy}
                        onChange={(e) =>
                          setParams({
                            ...params,
                            min_seconds: Number(e.target.value),
                          })
                        }
                      />
                    </label>
                    <label>
                      Máximo (s)
                      <input
                        type="number"
                        min={10}
                        max={180}
                        value={params.max_seconds}
                        disabled={busy}
                        onChange={(e) =>
                          setParams({
                            ...params,
                            max_seconds: Number(e.target.value),
                          })
                        }
                      />
                    </label>
                  </div>
                )}
                {busy ? (
                  <div className="upload-progress">
                    <div>
                      <span>Enviando seu vídeo</span>
                      <b>{Math.round(uploadProgress * 100)}%</b>
                    </div>
                    <progress value={uploadProgress} max={1} />
                    <button
                      className="text-button"
                      onClick={() => {
                        paused.current = true;
                        abort.current?.abort();
                      }}
                    >
                      <Pause size={14} />
                      Pausar envio
                    </button>
                  </div>
                ) : (
                  <button
                    className="primary create-button"
                    disabled={
                      !file ||
                      ai?.ai_configured === false ||
                      params.min_seconds > params.max_seconds
                    }
                    onClick={create}
                  >
                    <Sparkles size={18} />
                    {project?.status === "uploading"
                      ? "Continuar e criar cortes"
                      : "Criar cortes"}
                    <ArrowRight size={18} />
                  </button>
                )}
                {ai?.ai_configured === false ? (
                  <p className="setup-note">
                    Falta conectar a IA: configure GROQ_API_KEY no .env e
                    reinicie o aplicativo.
                  </p>
                ) : ai?.ai_provider === "local" ? (
                  <p className="privacy-note">
                    Tudo é processado neste computador, com IA local. Nada é
                    enviado para a internet.
                  </p>
                ) : (
                  <p className="privacy-note">
                    Seu vídeo fica neste servidor. Áudio e transcrição são
                    enviados ao Groq para criar os cortes.
                  </p>
                )}
                {project && !busy && (
                  <button
                    className="text-button danger"
                    onClick={() => setDeleting(true)}
                  >
                    <Trash2 size={14} />
                    Descartar envio
                  </button>
                )}
              </div>
              <div className="benefits">
                <span>
                  <Check size={15} />
                  Histórias com começo, meio e fim
                </span>
                <span>
                  <Check size={15} />
                  Prévia leve para revisar
                </span>
                <span>
                  <Check size={15} />
                  Original preservado
                </span>
              </div>
            </motion.section>
          ) : (
            <section className="project-screen">
              <div className="project-heading">
                <div>
                  <div className="eyebrow">SEU ESTÚDIO DE CORTES</div>
                  <h1>
                    {hasResults
                      ? "Boas histórias, prontas para sair."
                      : project?.status === "ready"
                        ? "Vamos tentar outra história?"
                        : "Encontrando o que vale contar."}
                  </h1>
                  <p className="file-caption">
                    <Film size={16} />
                    {project?.name}
                  </p>
                </div>
                <button className="secondary" onClick={fresh}>
                  <Plus size={16} />
                  Novo vídeo
                </button>
              </div>
              {processing && (
                <div className="processing-panel" role="status">
                  <div className="process-title">
                    <span className="activity-icon">
                      <Sparkles size={20} />
                    </span>
                    <div>
                      <strong>{project?.stage}</strong>
                      <p>
                        {project?.status === "queued"
                          ? "Seu vídeo está na fila. Você pode voltar depois."
                          : "Pode deixar com a gente. Seu progresso está sendo salvo."}
                      </p>
                    </div>
                    <button
                      className="text-button"
                      disabled={project?.status === "cancelling"}
                      onClick={() => action("cancel")}
                    >
                      <Pause size={15} />
                      Pausar
                    </button>
                  </div>
                  <div className="stage-list">
                    {stages.map((name, i) => (
                      <div
                        className={
                          stageIndex === i
                            ? "active"
                            : stageIndex > i
                              ? "done"
                              : ""
                        }
                        key={name}
                      >
                        <span>
                          {stageIndex > i ? <Check size={13} /> : i + 1}
                        </span>
                        {name}
                      </div>
                    ))}
                  </div>
                  <progress value={project?.progress || 0} max={1} />
                  <p aria-live="polite">
                    {Math.floor((project?.elapsed_seconds || 0) / 60)} min {Math.floor((project?.elapsed_seconds || 0) % 60)} s decorridos
                    {project?.units_total ? ` · ${project.units_done || 0}/${project.units_total} partes analisadas` : ""}
                    {project?.previews_ready ? ` · ${project.previews_ready} prévias prontas` : ""}
                  </p>
                </div>
              )}
              {project &&
                ["error", "cancelled", "uploaded"].includes(project.status) && (
                  <div className="recovery-panel">
                    <div>
                      <strong>
                        {project.status === "error"
                          ? "Vamos continuar de onde parou?"
                          : "Seu vídeo está salvo."}
                      </strong>
                      <p>
                        {project.error ||
                          "As etapas concluídas serão reaproveitadas."}
                      </p>
                    </div>
                    <button
                      className="primary"
                      onClick={() => action("start", project.params || params)}
                    >
                      <Play size={16} />
                      Continuar
                    </button>
                  </div>
                )}
              {project?.notice && <p className="notice">{project.notice}</p>}
              {hasResults && (
                <div className="results-label">
                  <span>
                    {readyCount}{" "}
                    {readyCount === 1 ? "prévia pronta" : "prévias prontas"}
                  </span>
                  <span>Revisão leve. Exportação em alta qualidade.</span>
                </div>
              )}
              <div className="clip-grid">
                {project?.clips.map((c, i) => (
                  <motion.article
                    className="clip-card"
                    key={c.id}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.25,
                      delay: Math.min(i * 0.05, 0.3),
                    }}
                  >
                    <div className="clip-player">
                      {c.preview_status === "ready" ? (
                        <video
                          controls
                          preload="metadata"
                          playsInline
                          src={`/api/projects/${project.id}/clips/${c.id}/preview`}
                          onPlay={(e) => {
                            document.querySelectorAll("video").forEach((v) => {
                              if (v !== e.currentTarget) v.pause();
                            });
                          }}
                        />
                      ) : (
                        <div className="preview-pending">
                          <LoaderCircle size={25} className="spin" />
                          <span>Preparando sua prévia</span>
                        </div>
                      )}
                      <span className="clip-number">
                        CORTE {String(i + 1).padStart(2, "0")}
                      </span>
                    </div>
                    <div className="clip-content">
                      <div className="clip-meta">
                        <span>HISTÓRIA COMPLETA</span>
                        <span>{duration(c.duration)}</span>
                      </div>
                      <h2>{c.title}</h2>
                      <p>{c.rationale}</p>
                      <div className="clip-actions">
                        {c.preview_status === "ready" ? (
                          <a
                            className="secondary"
                            href={`/api/projects/${project.id}/clips/${c.id}/preview?download=true`}
                          >
                            <ArrowDown size={16} />
                            Baixar prévia
                          </a>
                        ) : (
                          <button className="secondary" disabled>
                            Preparando prévia
                          </button>
                        )}
                        {c.original_status === "ready" ? (
                          <a
                            className="primary"
                            href={`/api/projects/${project.id}/clips/${c.id}/original?download=true`}
                          >
                            <ArrowDown size={16} />
                            Baixar original
                          </a>
                        ) : (
                          <button
                            className="primary"
                            title="Renderizado do vídeo original, sem limitar a resolução. A edição exige recodificação."
                            disabled={
                              c.preview_status !== "ready" ||
                              ["queued", "rendering"].includes(
                                c.original_status,
                              ) ||
                              project.status === "cancelled"
                            }
                            onClick={() => exportClip(c)}
                          >
                            {["queued", "rendering"].includes(
                              c.original_status,
                            ) ? (
                              <>
                                <LoaderCircle size={16} className="spin" />
                                {c.original_status === "queued"
                                  ? "Na fila"
                                  : `${Math.round((c.original_progress || 0) * 100)}% · Exportando`}
                              </>
                            ) : (
                              <>
                                <ArrowDown size={16} />
                                {c.original_status === "error"
                                  ? "Tentar exportar novamente"
                                  : "Baixar em qualidade original"}
                              </>
                            )}
                          </button>
                        )}
                      </div>
                      {c.original_error && (
                        <p className="inline-error" role="alert">
                          {c.original_error}
                        </p>
                      )}
                    </div>
                  </motion.article>
                ))}
              </div>
              {hasResults && (
                <p className="export-explainer">
                  A prévia é leve para assistir e compartilhar. A versão
                  original é renderizada em alta qualidade, na resolução do seu
                  vídeo.
                </p>
              )}
              <div className="project-footer">
                <span>Seu original permanece salvo neste servidor.</span>
                {exporting && !processing && (
                  <button
                    className="text-button"
                    onClick={() => action("cancel")}
                  >
                    <Pause size={14} /> Pausar exportações
                  </button>
                )}
                <button
                  className="text-button danger"
                  disabled={!!processing || uploading || exporting}
                  onClick={() => setDeleting(true)}
                >
                  <Trash2 size={14} />
                  Excluir projeto
                </button>
              </div>
            </section>
          )}
        </main>
        <footer>
          <span>CORTES STUDIO</span>
          <span>Menos tempo editando. Mais tempo criando.</span>
        </footer>
        {deleting && (
          <div className="modal-backdrop">
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="delete-title"
              className="modal"
              onKeyDown={(e) => {
                if (e.key === "Escape") setDeleting(false);
                if (e.key === "Tab") {
                  const buttons =
                    e.currentTarget.querySelectorAll<HTMLButtonElement>(
                      "button",
                    );
                  const first = buttons[0],
                    last = buttons[buttons.length - 1];
                  if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                  } else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                  }
                }
              }}
            >
              <h2 id="delete-title">Excluir este projeto?</h2>
              <p>
                O vídeo enviado, as prévias e as exportações serão removidos
                deste servidor. Seu arquivo no computador permanece intacto.
              </p>
              <div>
                <button
                  className="secondary"
                  autoFocus
                  onClick={() => setDeleting(false)}
                >
                  Voltar
                </button>
                <button className="primary" onClick={remove}>
                  Excluir projeto
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </MotionConfig>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
