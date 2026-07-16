import { useQuery } from "@tanstack/react-query";
import { Eye, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ImagingModality, ImagingPreview as ImagingPreviewType } from "../types";

function SliceCanvas({ modality, preview }: { modality: ImagingModality; preview: ImagingPreviewType }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const [height, width] = preview.shape;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) return;
    const image = context.createImageData(width, height);
    for (let row = 0; row < height; row += 1) {
      for (let column = 0; column < width; column += 1) {
        const offset = (row * width + column) * 4;
        const intensity = modality.pixels[row][column];
        const label = preview.label_pixels[row][column];
        if (label === 1) {
          image.data[offset] = Math.min(255, intensity * 0.55 + 30);
          image.data[offset + 1] = Math.min(255, intensity * 0.55 + 165);
          image.data[offset + 2] = Math.min(255, intensity * 0.55 + 115);
        } else if (label >= 2) {
          image.data[offset] = Math.min(255, intensity * 0.5 + 190);
          image.data[offset + 1] = Math.min(255, intensity * 0.5 + 75);
          image.data[offset + 2] = Math.min(255, intensity * 0.5 + 35);
        } else {
          image.data[offset] = intensity;
          image.data[offset + 1] = intensity;
          image.data[offset + 2] = intensity;
        }
        image.data[offset + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
  }, [modality, preview]);
  return (
    <figure className="modality-view">
      <canvas ref={canvasRef} aria-label={`${modality.name} synthetic MRI preview`} />
      <figcaption><strong>{modality.name}</strong><small>AXIAL · SLICE {preview.slice_index}</small></figcaption>
    </figure>
  );
}

export default function ImagingPreview({ studyId }: { studyId: string }) {
  const [site, setSite] = useState("site-a");
  const preview = useQuery({
    queryKey: ["imaging-preview", studyId, site],
    queryFn: () => api.imagingPreview(studyId, site),
  });
  return (
    <section className="panel imaging-panel">
      <div className="panel-title">
        <div><Eye size={18} /><span><strong>四模态本地感知</strong><small>合成 NIfTI · 标签叠加 · 像素数据不进入 Step 3.7</small></span></div>
        <div className="site-switcher">
          {["site-a", "site-b", "site-c"].map((item) => (
            <button className={site === item ? "active" : ""} key={item} onClick={() => setSite(item)}>{item.toUpperCase()}</button>
          ))}
        </div>
      </div>
      {preview.isLoading && <div className="placeholder">正在本地生成四模态预览…</div>}
      {preview.error && <div className="placeholder">{preview.error instanceof Error ? preview.error.message : "预览不可用"}</div>}
      {preview.data && (
        <>
          <div className="modality-grid">{preview.data.modalities.map((item) => <SliceCanvas key={item.name} modality={item} preview={preview.data} />)}</div>
          <div className="imaging-boundary"><ShieldCheck size={14} /><span>仅合成演示数据 · {preview.data.case_id} · 间距 {preview.data.spacing?.join(" × ")} · <strong>LLM EGRESS: BLOCKED</strong></span><em><i /> 水肿/外围区域 <i /> 肿瘤核心</em></div>
        </>
      )}
    </section>
  );
}
