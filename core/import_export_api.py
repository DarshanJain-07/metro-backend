from pathlib import Path

import tablib
from django.conf import settings
from django.http import HttpResponse
from import_export.formats import base_formats
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.request_context import get_current_company, get_current_office, get_current_role


FORMAT_CLASSES = {
    "csv": base_formats.CSV,
    "xlsx": base_formats.XLSX,
}
DEFAULT_MAX_UPLOAD_SIZE = 10 * 1024 * 1024


def get_file_format(format_name):
    try:
        return FORMAT_CLASSES[format_name.lower()]()
    except KeyError:
        raise serializers.ValidationError({"format": "Supported formats are csv and xlsx."})


def detect_import_format(uploaded_file, request):
    requested = request.data.get("format")
    if requested:
        return get_file_format(str(requested))

    extension = Path(uploaded_file.name).suffix.lower().lstrip(".")
    if extension == "xls":
        extension = "xlsx"
    return get_file_format(extension)


def format_file_size(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.0f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} bytes"


def validate_import_file_size(uploaded_file):
    max_size = getattr(settings, "IMPORT_EXPORT_MAX_UPLOAD_SIZE", DEFAULT_MAX_UPLOAD_SIZE)
    if uploaded_file.size and uploaded_file.size > max_size:
        raise serializers.ValidationError(
            {
                "file": (
                    f"Import file is too large. Maximum allowed size is "
                    f"{format_file_size(max_size)}."
                )
            }
        )


def dataset_from_rows(rows):
    headers = []
    for row in rows:
        for key in row.keys():
            if key.startswith("_"):
                continue
            if key not in headers:
                headers.append(key)

    dataset = tablib.Dataset(headers=headers)
    for row in rows:
        dataset.append([row.get(header) for header in headers])
    return dataset


def import_result_payload(result):
    errors = []
    for row_number, row_errors in result.row_errors():
        errors.append(
            {
                "row": row_number,
                "errors": [str(error.error) for error in row_errors],
            }
        )
    for invalid_row in result.invalid_rows:
        errors.append(
            {
                "row": invalid_row.number,
                "errors": invalid_row.error_dict,
            }
        )
    for base_error in result.base_errors:
        errors.append({"row": None, "errors": [str(base_error.error)]})

    return {
        "total_rows": result.total_rows,
        "totals": dict(result.totals),
        "errors": errors,
    }


class ImportExportViewSetMixin:
    import_export_resource_class = None
    export_filename = None

    def get_import_export_resource_class(self):
        if self.import_export_resource_class is None:
            raise AssertionError("import_export_resource_class must be set.")
        return self.import_export_resource_class

    def get_import_export_context(self):
        return {
            "company": get_current_company(),
            "user": self.request.user,
            "office": get_current_office(self.request.user),
            "role": get_current_role(),
        }

    def get_import_export_resource(self):
        return self.get_import_export_resource_class()(**self.get_import_export_context())

    def run_dataset_import(self, dataset):
        resource = self.get_import_export_resource()
        result = resource.import_data(
            dataset,
            dry_run=False,
            raise_errors=False,
            use_transactions=True,
            rollback_on_validation_errors=True,
            **self.get_import_export_context(),
        )
        payload = import_result_payload(result)
        if result.has_errors() or result.has_validation_errors():
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="import-file")
    def import_file(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            raise serializers.ValidationError({"file": "Upload a CSV or XLSX file."})

        validate_import_file_size(uploaded_file)
        file_format = detect_import_format(uploaded_file, request)
        dataset = tablib.Dataset().load(uploaded_file.read(), format=file_format.get_title())
        return self.run_dataset_import(dataset)

    @action(detail=False, methods=["get"], url_path="export")
    def export_file(self, request, *args, **kwargs):
        format_name = request.query_params.get("format", "csv").lower()
        file_format = get_file_format(format_name)
        resource = self.get_import_export_resource()
        dataset = resource.export(self.get_queryset(), **self.get_import_export_context())
        exported = file_format.export_data(dataset)
        content_type = file_format.get_content_type()
        response = HttpResponse(exported, content_type=content_type)
        filename = self.export_filename or self.basename if hasattr(self, "basename") else "export"
        response["Content-Disposition"] = f'attachment; filename="{filename}.{file_format.get_extension()}"'
        return response
