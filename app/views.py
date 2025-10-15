from django.shortcuts import render
import csv
from io import StringIO
import os
import tempfile

# Create your views here.
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from app.utils.invoice_processor import process_multiple_invoices
from app.utils.store_database import store_invoice_data, list_invoices
from .tasks import process_invoice_async

@csrf_exempt
def list_invoices_api(request):
	"""API endpoint to return all stored invoices as JSON."""
	if request.method != "GET":
		return JsonResponse({"error": "Only GET allowed"}, status=405)
	try:
		invoices = list_invoices(limit=100)
		# Convert ObjectId to string for JSON serialization
		for inv in invoices:
			inv["_id"] = str(inv["_id"])
		return JsonResponse({"invoices": invoices}, safe=False)
	except Exception as e:
		return JsonResponse({"error": str(e)}, status=500)
from django.shortcuts import render


@csrf_exempt
def upload_invoice(request):
    """API endpoint to upload one or more invoice images, process them in parallel,
    and return results for each file.

    Expected: POST with file field(s) named 'files' (multipart/form-data).
    Can handle both single and multiple file uploads.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({"error": "No files uploaded. Please include files in 'files' field."}, status=400)

    try:
        # Process all files in parallel using group and apply_async
        from celery import group
        
        # Prepare tasks for parallel execution
        tasks = []
        for file in files:
            try:
                # Read file content first - must seek to beginning to read
                file.seek(0)
                file_content = file.read()
                
                # Validate file content
                if not file_content:
                    return JsonResponse({
                        "error": f"Empty file uploaded: {file.name}"
                    }, status=400)
                
                # Add task to the list for parallel processing
                tasks.append(process_invoice_async.s(file_content, file.name))
            except Exception as e:
                return JsonResponse({
                    "error": f"Error processing file {file.name}: {str(e)}"
                }, status=400)
        
        # Execute all tasks in parallel
        try:
            if tasks:
                # Use group to run all tasks in parallel
                job = group(tasks)
                result = job.apply_async()
                task_ids = [str(task_id) for task_id in result.children]
            else:
                task_ids = []
        except Exception as e:
            return JsonResponse({
                "error": f"Error starting parallel tasks: {str(e)}"
            }, status=500)

        return JsonResponse({
            "message": "Files uploaded successfully for parallel processing",
            "task_ids": task_ids
        })

    except Exception as e:
        return JsonResponse({
            "error": "Upload failed",
            "details": str(e)
        }, status=500)


@csrf_exempt
def download_csv(request):
	"""API endpoint to download all invoices as CSV."""
	if request.method != "GET":
		return JsonResponse({"error": "Only GET allowed"}, status=405)
	
	try:
		invoices = list_invoices(limit=1000)  # Get more invoices for CSV
		
		# Create CSV content
		output = StringIO()
		writer = csv.writer(output)
		
		# Find max number of items across all invoices
		max_items = 0
		for inv in invoices:
			invoice_data = inv.get('invoice_data', {})
			items = invoice_data.get('Invoice Items', [])
			max_items = max(max_items, len(items))

		# Prepare header row with dynamic item columns
		header = [
			'Date', 'Vendor Name', 'Vendor Address', 'Vendor Tax Number', 
			'Invoice Number', 'Invoice Date', 'Type of Invoice'
		]
		
		# Add item headers dynamically
		for i in range(max_items):
			item_num = i + 1
			header.extend([
				f'Item {item_num} Name',
				f'Item {item_num} Quantity',
				f'Item {item_num} HSN/SAC',
				f'Item {item_num} Rate'
			])
		
		# Add total columns at the end
		header.extend(['Total Invoice Value', 'GST Value', 'Source Image'])
		
		# Write header
		writer.writerow(header)
		
		# Write data rows
		for inv in invoices:
			invoice_data = inv.get('invoice_data', {})
			vendor = invoice_data.get('Vendor Details', {})
			details = invoice_data.get('Invoice Details', {})
			items = invoice_data.get('Invoice Items', [])
			overall = invoice_data.get('Overall', {})
			
			# Start with the common fields
			row = [
				inv.get('processed_at', ''),
				vendor.get('Name', ''),
				vendor.get('Address', ''),
				vendor.get('Tax Number', ''),
				details.get('Invoice Number', ''),
				details.get('Invoice Date', ''),
				details.get('Type of Invoice', '')
			]
			
			# Add item details
			for i in range(max_items):
				if i < len(items):
					item = items[i]
					row.extend([
						item.get('Name', ''),
						item.get('Quantity', ''),
						item.get('HSN_SAC_code', ''),
						item.get('Rate', '')
					])
				else:
					# Fill empty values for invoices with fewer items
					row.extend(['', '', '', ''])
			
			# Add the total fields
			row.extend([
				overall.get('Total Invoice Value', ''),
				overall.get('GST Value', ''),
				inv.get('source_image', '')
			])
			
			writer.writerow(row)
		
		# Create HTTP response with CSV
		response = HttpResponse(output.getvalue(), content_type='text/csv')
		response['Content-Disposition'] = 'attachment; filename="invoices.csv"'
		return response
		
	except Exception as e:
		return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def check_task_status(request, task_id):
    """API endpoint to check the status of a processing task."""
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)
    
    try:
        task = process_invoice_async.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                return JsonResponse({
                    "status": "completed",
                    "result": task.get()
                })
            else:
                return JsonResponse({
                    "status": "failed",
                    "error": str(task.result)
                })
        else:
            return JsonResponse({
                "status": "processing"
            })
    except Exception as e:
        return JsonResponse({
            "error": "Status check failed",
            "details": str(e)
        }, status=500)

@csrf_exempt
def check_all_tasks_status(request):
    """API endpoint to check the status of all processing tasks from a group."""
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)
    
    try:
        # Get task IDs from query parameters
        task_ids = request.GET.getlist('task_id')
        if not task_ids:
            return JsonResponse({"error": "No task IDs provided"}, status=400)
        
        results = {}
        for task_id in task_ids:
            task = process_invoice_async.AsyncResult(task_id)
            if task.ready():
                if task.successful():
                    results[task_id] = {
                        "status": "completed",
                        "result": task.get()
                    }
                else:
                    results[task_id] = {
                        "status": "failed",
                        "error": str(task.result)
                    }
            else:
                results[task_id] = {
                    "status": "processing"
                }
                
        # Calculate overall progress
        completed = sum(1 for r in results.values() if r["status"] in ["completed", "failed"])
        total = len(results)
        progress_percent = (completed / total) * 100 if total > 0 else 0
                
        return JsonResponse({
            "tasks": results,
            "progress": {
                "completed": completed,
                "total": total,
                "percent": progress_percent
            }
        })
    except Exception as e:
        return JsonResponse({
            "error": "Status check failed",
            "details": str(e)
        }, status=500)

def upload_page(request):
    """Render a small test page for uploading invoices."""
    return render(request, "upload.html")

