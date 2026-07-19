#!/usr/bin/env bash
set -euo pipefail

# Launch an OpenAI-compatible TensorRT-LLM endpoint on the DGX Spark host.
# Run this on Spark after sourcing deploy/spark-local-llm.env.example copied to
# a private .env file.  The model is downloaded by the Spark node itself.

: "${HF_TOKEN:?Set HF_TOKEN in a private env file after accepting the model license.}"
MODEL_HANDLE="${MODEL_HANDLE:-nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4}"
TRTLLM_IMAGE="${TRTLLM_IMAGE:-nvcr.io/nvidia/tensorrt-llm/release:1.3.0rc13}"
TRTLLM_PORT="${TRTLLM_PORT:-8355}"
MAX_BATCH_SIZE="${MAX_BATCH_SIZE:-8}"
CACHE_DIR="${HF_HOME:-$HOME/.cache/huggingface}"

mkdir -p "$CACHE_DIR"
echo "Starting local TensorRT-LLM on port ${TRTLLM_PORT} with ${MODEL_HANDLE}"
echo "Model weights are fetched directly by this Spark node; no SSH/SCP upload is used."

docker run --rm --gpus all --network host \
  --name rarelink-trtllm \
  -v "$CACHE_DIR:/root/.cache/huggingface" \
  -e HF_TOKEN \
  -e HUGGINGFACE_HUB_TOKEN="$HF_TOKEN" \
  "$TRTLLM_IMAGE" bash -lc "
    hf download '$MODEL_HANDLE' &&
    cat > /tmp/rarelink-trtllm.yml <<'EOF'
kv_cache_config:
  dtype: auto
  free_gpu_memory_fraction: 0.82
cuda_graph_config:
  enable_padding: true
disable_overlap_scheduler: true
EOF
    trtllm-serve '$MODEL_HANDLE' \
      --host 127.0.0.1 \
      --port '$TRTLLM_PORT' \
      --max_batch_size '$MAX_BATCH_SIZE' \
      --trust_remote_code \
      --extra_llm_api_options /tmp/rarelink-trtllm.yml
  "
