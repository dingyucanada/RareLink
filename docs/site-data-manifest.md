# RareLink 医院本地 NIfTI 数据规范

> 本规范只适用于受控科研环境的首个正式数据路径。它不定义 PACS/DICOM
> 临床接口，不允许中心控制面接收 manifest 原文、病例标识或影像像素。

## 1. 目录与所有权

每家医院维护独立的数据根目录、manifest 和数据证明。例如：

```text
/srv/rarelink/site-data/
├── manifest.json
├── local-case-001/
│   ├── flair.nii.gz
│   ├── t1.nii.gz
│   ├── t1ce.nii.gz
│   ├── t2.nii.gz
│   └── label.nii.gz
└── local-case-002/...
```

数据根目录只挂载到该院 Spark。协调端、Agent、Git 仓库和公共演示不得挂载
或复制该目录。manifest 中每条记录的 `site_id` 必须等于本站配置的 Site ID。

## 2. Manifest v1

```json
{
  "schema_version": "rarelink-site-manifest-v1",
  "modalities": ["FLAIR", "T1w", "T1wCE", "T2w"],
  "allowed_label_values": [0, 1, 2],
  "cases": [
    {
      "case_id": "local-opaque-001",
      "site_id": "hospital-a",
      "images": [
        "local-case-001/flair.nii.gz",
        "local-case-001/t1.nii.gz",
        "local-case-001/t1ce.nii.gz",
        "local-case-001/t2.nii.gz"
      ],
      "label": "local-case-001/label.nii.gz"
    }
  ]
}
```

`images` 可以是四个已配准的三维 NIfTI，也可以是一个最后一维为 4 的四维
NIfTI。`case_id` 只在医院本地使用，应为随机、不透明研究编号，不能使用病历号、
姓名、身份证、检查号或 DICOM UID。它不会进入数据证明或中心 API。

如果原始标签需要映射，可用 `label_mapping` 替代 `allowed_label_values`：

```json
{"label_mapping": {"0": 0, "1": 1, "2": 2, "3": 2}}
```

键定义源标签允许值；训练代码继续按合同执行映射。

## 3. 强制拒绝条件

验证器在训练前拒绝：

- manifest 混入其他 `site_id`；
- `patient_name`、`patient_id`、`mrn`、`accession_number`、DICOM
  Study/Series UID、出生日期、电话或邮箱等直接标识字段；
- 绝对路径或相对路径逃逸到批准的数据根目录之外；
- 符号链接、缺失文件、非 `.nii/.nii.gz` 文件；
- 不是“四个三维模态”或“一个四通道图像”的输入；
- MRI 与标签 shape、affine 或 orientation 不一致；
- 非正数/非有限 spacing；
- 非三维标签、非整数标签、NaN/Inf 或超出标签合同的取值。

检查在医院本地执行。错误响应使用类别化原因，不回传病例编号或路径。

## 4. 生成并核验数据证明

```bash
python3 scripts/validate_site_dataset.py \
  --manifest /srv/rarelink/site-data/manifest.json \
  --data-root /srv/rarelink/site-data \
  --site-id hospital-a \
  --output /var/lib/rarelink/site-agent/dataset-receipt.json
```

验证器使用 nibabel 读取 NIfTI header/标签，并生成：

- manifest SHA-256；
- manifest 与所有声明文件内容共同形成的 `dataset_fingerprint`；
- manifest、文件顺序、size 和 mtime 形成的快速状态指纹；
- 病例数、文件数、shape/spacing/orientation 变体数；
- 允许与实际观察到的标签集合；
- 明确的“无病例 ID、无路径、无影像/标签体素外发”标志。

证明不包含 case ID、文件名、路径、影像哈希列表或病例级指标。Site Agent
心跳只携带数据指纹和证明哈希。每次正式训练启动时，FLARE Client 会重新核验
文件内容指纹，而不是只相信旧证明。

## 5. 版本失效规则

物理作业在人工批准前固定三家站点各自的 `dataset_fingerprint`。以下任一变化
都会使旧证明或旧作业失效：

- manifest 内容、站点归属、模态或标签合同变化；
- 任一声明文件的内容、size 或 mtime 变化；
- 数据证明缺失、被替换、安全标志异常或 Site ID 不匹配；
- 站点从 `READY` 变为 `DEGRADED/OFFLINE`。

失效后的作业不能 retry/resume 以绕过合同；必须重新验证数据、创建新作业并
重新人工批准。该机制证明数据版本与作业合同一致，不证明数据来源合法、标签
医学正确或模型具备临床有效性。
