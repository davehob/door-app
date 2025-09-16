from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo

def build_order_excel(order, items):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Door Order"; ws["A1"].font = Font(size=16, bold=True)
    ws["A3"] = "Job ID"; ws["B3"] = order.job_id
    ws["A4"] = "Order ID"; ws["B4"] = order.id

    ws2 = wb.create_sheet("Items")
    headers = ["Line","Type","Style","Qty","Width (in)","Height (in)","Notes/Hinge","Source Page"]
    ws2.append(headers)
    for i, it in enumerate(items, start=1):
        ws2.append([i, it.type, it.style, it.qty, it.width_in, it.height_in, it.note, it.source_page])

    ref = f"A1:H{len(items)+1}"
    tbl = Table(displayName="tbl_items", ref=ref)
    tbl.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws2.add_table(tbl)
    for col in "ABCDEFGH":
        ws2.column_dimensions[col].width = 15
    ws2.freeze_panes = "A2"
    return wb
