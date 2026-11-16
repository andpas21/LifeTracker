"""Esportazione delle registrazioni in CSV ed Excel (rispetta filtri e visibilità)."""
from __future__ import annotations

import csv
import io
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.extensions import db
from app.models import ActivityEntry
from app.services import entry_service, stats_service
from app.services.entry_service import EntryFilters
from app.utils.timezone import to_local

BASE_COLUMNS = ["ID", "Data", "Ora", "Categoria", "Attività", "Svolta da", "Inserita da", "Quantità", "Unità",
                "Ambito", "Visibilità", "Descrizione", "Note", "Tag", "Partecipanti", "Allegati"]


def _entries(actor, filters: EntryFilters) -> list[ActivityEntry]:
    return list(db.session.scalars(entry_service.filtered_query(actor, filters)))


def _rows(entries):
    metric_columns = {}
    for e in entries:
        for v in e.metric_values:
            d = v.definition
            unit = "h:mm" if d.data_type == "duration" else (d.unit or "")
            metric_columns.setdefault(d.id, f"{d.activity.name} · {d.name}{' (' + unit + ')' if unit else ''}")
    header = BASE_COLUMNS + list(metric_columns.values())
    rows = []
    for e in sorted(entries, key=lambda x: x.occurred_at):
        local = to_local(e.occurred_at)
        values = {v.metric_definition_id: v for v in e.metric_values}
        row = [
            e.id, local.date(), local.strftime("%H:%M"), e.activity.category.full_name, e.activity.name,
            e.performed_by.display_name, e.created_by.display_name if e.created_by else "",
            float(e.quantity), e.activity.count_label, "Familiare" if e.scope == "family" else "Personale",
            "Famiglia" if e.visibility == "family" else "Privata", e.description or "", e.notes or "",
            ", ".join(t.name for t in e.tags), ", ".join(p.display_name for p in e.participants), len(e.attachments),
        ]
        for metric_id in metric_columns:
            v = values.get(metric_id)
            if v is None:
                row.append("")
            elif v.definition.data_type == "text":
                row.append(v.value_text or "")
            elif v.definition.data_type == "duration":
                row.append(entry_service.format_metric_value(v))
            elif v.definition.data_type == "boolean":
                row.append("Sì" if v.value_numeric else "No")
            else:
                row.append(float(v.value_numeric))
        rows.append(row)
    return header, rows


def to_csv(actor, filters: EntryFilters) -> bytes:
    header, rows = _rows(_entries(actor, filters))
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")  # il punto e virgola è lo standard di Excel in italiano
    writer.writerow(header)
    for row in rows:
        writer.writerow([str(c).replace(".", ",") if isinstance(c, float) else
                         (c.strftime("%d/%m/%Y") if hasattr(c, "strftime") else c) for c in row])
    return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM: Excel riconosce gli accenti


def to_xlsx(actor, filters: EntryFilters) -> bytes:
    entries = _entries(actor, filters)
    header, rows = _rows(entries)
    wb = Workbook()
    ws = wb.active
    ws.title = "Registrazioni"
    ws.append(header)
    for row in rows:
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    for idx in range(1, len(header) + 1):
        ws.column_dimensions[get_column_letter(idx)].width = 16
    for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = "DD/MM/YYYY"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    summary = wb.create_sheet("Riepilogo")
    summary.append(["Attività", "Registrazioni", "Quantità", "Unità", "Tempo dedicato"])
    groups = stats_service.group_by(entries, lambda e: e.activity_id)
    for items in sorted(groups.values(), key=lambda i: -len(i)):
        a = items[0].activity
        summary.append([a.name, len(items), float(sum(e.quantity for e in items)), a.count_label,
                        stats_service.fmt_hours(stats_service.duration_seconds(items))])
    summary.append([])
    summary.append(["Persona", "Registrazioni"])
    for name, n in Counter(e.performed_by.display_name for e in entries).most_common():
        summary.append([name, n])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 28
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
