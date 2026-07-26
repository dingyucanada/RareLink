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
  --split-seed 2026 \
  --validation-fraction 0.2 \
  --output /var/lib/rarelink/site-agent/dataset-receipt.json
```

验证器使用 nibabel 读取 NIfTI header/标签，并生成：

- manifest SHA-256；
- manifest 与所有声明文件内容共同形成的 `dataset_fingerprint`；
- manifest、文件顺序、size 和 mtime 形成的快速状态指纹；
- 病例数、文件数、shape/spacing/orientation 变体数；
- 允许与实际观察到的标签集合；
- 基于 seed 的确定性训练/验证数量、算法与整体 assignment SHA-256；
- 明确的“无病例 ID、无路径、无影像/标签体素外发”标志。

证明不包含 case ID、文件名、路径、影像哈希列表或病例级指标。Site Agent
心跳只携带数据指纹和证明哈希。每次正式训练启动时，FLARE Client 会重新核验
文件内容指纹，而不是只相信旧证明。

划分算法为 `seeded-sha256-rank-v1`：使用 seed 和本站不透明 `case_id` 生成稳定
排序，按 `validation_fraction` 选择验证集。它不依赖 manifest 顺序或 Python
进程随机状态。数据证明只记录训练/验证数量和整个 assignment 的绑定摘要，
不记录任一病例的分组、标识或单病例哈希。seed、比例、病例集合发生变化时，
旧数据证明失效。MONAI 单站训练和 NVFLARE Client 使用同一算法，不再依赖
“最后一例作为验证集”的隐式顺序。

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

## 6. 可重复 MONAI 预处理与本地缓存

`rarelink.site_data.materialize_monai_preprocessing_cache` 在生成缓存前执行完整
数据证明核验，然后使用 MONAI `PersistentDataset` 建立医院本地持久缓存。v1
计划固定：

- `LoadImaged` 和 `EnsureChannelFirstd`；
- RAS orientation；
- 图像 bilinear、标签 nearest 的目标 spacing 重采样；
- 图像按通道、非零区域 z-score；
- 标签按 manifest 合同确定性映射；
- 常量 padding 到指定空间倍数；
- tensor 转换；
- 不包含随机 transform。

计划包含 MONAI 版本和全部参数，并计算 `preprocessing_plan_sha256`。缓存证明
绑定数据指纹、划分证明、计划摘要、缓存项数、文件数、总字节数和整体内容摘要。
它不包含病例 ID、源文件名、缓存文件名、路径或体素。缓存目录必须位于医院本地
受控存储，不得挂载到协调端。

示例：

```python
from pathlib import Path
from rarelink.site_data import materialize_monai_preprocessing_cache

receipt = materialize_monai_preprocessing_cache(
    Path("/srv/rarelink/site-data/manifest.json"),
    Path("/var/lib/rarelink/site-agent/dataset-receipt.json"),
    site_id="hospital-a",
    data_root=Path("/srv/rarelink/site-data"),
    cache_root=Path("/var/cache/rarelink/monai"),
)
```

## 7. BIDS 本地映射

BIDS 入口使用可选依赖 PyBIDS 建立标准感知索引，并要求数据管理员为 FLAIR、
T1w、T1wCE、T2w 和 segmentation 显式提供 entity query。每个 subject/session
组合的每个角色必须恰好匹配一个本地 NIfTI；模糊匹配、路径逃逸、符号链接、
非 NIfTI 和不足两例均默认拒绝。

适配器要求一个至少 32 字节的站点本地 `case_id_key`，使用 HMAC 为 BIDS
subject/session 生成稳定、不透明的 RareLink `case_id`。密钥、subject、session
和路径不进入映射证明。生成的 manifest 仍是医院本地文件，可能引用 BIDS 本地
相对路径，因此不得上传至中心或 Git。

```python
from rarelink.site_data import import_bids_manifest

receipt = import_bids_manifest(
    bids_root,
    output_manifest,
    site_id="hospital-a",
    modality_queries={
        "FLAIR": {"suffix": "FLAIR"},
        "T1w": {"suffix": "T1w"},
        "T1wCE": {"suffix": "T1wCE"},
        "T2w": {"suffix": "T2w"},
    },
    label_query={"suffix": "seg", "scope": "derivatives"},
    case_id_key=site_local_secret,
)
```

若 PyBIDS 未安装，入口明确失败，不退化为文件名猜测。

## 8. DICOM Header 去标识检查与 NIfTI 入口边界

DICOM 能力只检查已暂存的本地文件，不连接 PACS，也不执行 DICOM-to-NIfTI
转换。默认 reader 使用 pydicom：

- `stop_before_pixels=True`，不得读取 Pixel Data；
- `PatientIdentityRemoved` 必须为 `YES`；
- `BurnedInAnnotation` 必须为 `NO`；
- 必须声明 `DeidentificationMethod`；
- PatientName、PatientID、AccessionNumber、出生日期、电话、转诊医生等直接
  标识字段必须为空；
- 去标识后仍存在的私有标签默认拒绝；
- Study/Series/SOP UID 可以作为 DICOM 结构的一部分在本地 Header 中存在，
  但具体 UID 永不进入证明、日志或 NIfTI manifest 元数据。

Header 证明只包含文件数、整体绑定摘要和布尔安全结论。随后
`validate_nifti_intake_boundary` 可以把该证明摘要与已经由医院批准工具转换完成的
NIfTI 数据证明绑定；此函数不会伪装成转换器。

## 9. 安装与明确未实现项

医院数据节点安装独立可选依赖：

```bash
pip install -e '.[site-data]'
```

该 extra 包含 MONAI、nibabel、NumPy、pydicom 和 PyBIDS。未安装 pydicom 或
PyBIDS 时，对应入口 fail closed。

当前版本明确没有实现：

- PACS 查询、DICOM C-FIND/C-MOVE、DICOMweb；
- FHIR ResearchStudy、ImagingStudy 或患者资源同步；
- DICOM-to-NIfTI 转换和序列配准；
- 医院身份映射、伦理审批、数据使用授权或临床诊断。

这些能力需要医院接口、合规和医学验证独立立项，不能用本地文件适配器替代。
