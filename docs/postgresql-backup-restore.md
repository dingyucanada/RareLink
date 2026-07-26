# PostgreSQL 备份与恢复

RareLink 使用 PostgreSQL custom-format 归档，凭据只存在受保护的 `PGSERVICEFILE`
或 `.pgpass` 中，不把完整连接 URL、密码或 Token放进命令行、Manifest、日志或收据。

## 1. 备份

准备权限为 `0600` 的服务文件：

```ini
[rarelink-production]
host=postgres.internal
port=5432
dbname=rarelink_control
user=rarelink_backup
sslmode=verify-full
sslrootcert=/protected/ca.pem
```

密码放在权限 `0600` 的 `.pgpass` 或医院 Secret Manager，不写入上述示例。

```bash
PGSERVICEFILE=/protected/pg_service.conf \
python scripts/postgres_backup.py \
  --service rarelink-production \
  --output /protected/backups/rarelink-2026-07-26.dump
```

执行器先读取 Alembic revision，只有与当前发布一致才调用 `pg_dump`。归档原子替换、
权限固定为 `0600`，并产生绑定文件名、大小、SHA-256 和 schema revision 的 Manifest。

## 2. 恢复演练

恢复必须指向单独的验证库，并两次输入完全相同的服务名：

```bash
PGSERVICEFILE=/protected/pg_service.conf \
python scripts/postgres_restore.py \
  --backup /protected/backups/rarelink-2026-07-26.dump \
  --manifest /protected/backups/rarelink-2026-07-26.manifest.json \
  --target-service rarelink-restore-verify \
  --confirm-target-service rarelink-restore-verify
```

恢复前重新计算归档 SHA-256；`pg_restore` 使用 `--exit-on-error --clean --if-exists
--no-owner --no-privileges`；恢复后重新检查 Alembic revision。目标名确认不一致、
权限过宽、符号链接、摘要变化或 revision 错误都会失败关闭。

## 3. 正式验收

医院试点必须另外完成：

- 加密备份介质与密钥恢复；
- PITR/WAL 归档；
- RPO/RTO 目标；
- 跨主机恢复；
- 数据库与 coordinator artifacts 的一致性；
- 备份保留、销毁和访问审计；
- 恢复后 API、审计链、模型发布和证据包抽样核验。

仓库的 fake-tool 自动测试验证命令、安全边界与篡改阻断，不代替真实 PostgreSQL
容量、备份介质或灾难恢复演练。
