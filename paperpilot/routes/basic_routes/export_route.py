"""
Data export routing
Export function for processing papers and configuration data
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, Response, jsonify, request, send_file
from werkzeug.utils import secure_filename


# Export task status storage
export_tasks: Dict[str, Dict[str, Any]] = {}
export_tasks_lock = threading.Lock()

# Currently active export tasksID
current_export_task_id: Optional[str] = None


def _should_exclude_file(rel_path: str) -> bool:
    """Determine whether the file should be excluded (export only JSON metadata and directory structure)"""
    # Exclude temporary directories and index files (but keep .avatars）
    excluded_dirs = ['.daily_arxiv_temp', '.temp']
    excluded_files = ['.search_index.db', '.search_index.db.corrupted']
    
    # Check if in excluded directory
    path_parts = rel_path.split(os.sep)
    for excluded_dir in excluded_dirs:
        if excluded_dir in path_parts:
            return True
    
    # Check if it is an excluded file
    filename = os.path.basename(rel_path)
    if filename in excluded_files:
        return True
    
    # only keep JSON files, directory structures and .avatars
    # exclude all PDF、outputs Table of contents,_analysis.md、_images folder
    if filename.endswith('.pdf'):
        return True
    if 'outputs' in path_parts:
        return True
    if filename.endswith('_analysis.md') or '_images' in path_parts:
        return True
    
    return False


def _export_papers_folder_to_zip(
    papers_dir: str,
    zip_path: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
):
    """will the entire papers of folder JSON Metadata is exported to ZIP file, retaining the original directory structure"""
    print(f"[Export] Start exporting folder metadata: {papers_dir}")
    
    # Calculate total number of files
    total_files = 0
    for root, dirs, files in os.walk(papers_dir):
        dirs[:] = [d for d in dirs if d not in ['.daily_arxiv_temp', '.temp']]
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, papers_dir)
            if not _should_exclude_file(rel_path):
                total_files += 1
    
    print(f"[Export] Found in total {total_files} files")
    
    # Start packing
    processed_files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(papers_dir):
            # Exclude temporary directory
            dirs[:] = [d for d in dirs if d not in ['.daily_arxiv_temp', '.temp']]
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, papers_dir)
                
                # Check if it should be excluded
                if _should_exclude_file(rel_path):
                    continue
                
                # add to ZIP
                zip_file_path = f"papers/{rel_path}"
                try:
                    zipf.write(file_path, zip_file_path)
                    processed_files += 1
                    
                    if progress_callback and processed_files % 10 == 0:
                        progress_callback(processed_files, total_files, f"Packing: {rel_path}")
                except Exception as e:
                    print(f"[Export] Failed to package file: {file_path}, mistake: {e}")
    
    print(f"[Export] Packaging completed and processed in total {processed_files} files")


def register_export_routes(
    app: Flask,
    papers_dir: str,
):
    """Register and export related routes"""
    
    @app.route("/api/export/start", methods=["POST"])
    def api_export_start():
        """Start export task"""
        global current_export_task_id
        
        # Check if there is already an export task running
        with export_tasks_lock:
            if current_export_task_id and current_export_task_id in export_tasks:
                task = export_tasks[current_export_task_id]
                if task["status"] in ["running", "pending"]:
                    return jsonify({
                        "success": False,
                        "error": "An export task is already running",
                        "task_id": current_export_task_id
                    }), 400
        
        # Export options fixed to export only JSON metadata
        export_options = {}  # Options no longer needed
        
        # Create taskID
        task_id = f"export_{int(time.time() * 1000)}"
        
        # Initialize task status
        with export_tasks_lock:
            export_tasks[task_id] = {
                "task_id": task_id,
                "status": "pending",
                "progress": 0,
                "total": 0,
                "current_paper": "",
                "error": None,
                "zip_path": None,
                "options": export_options,
                "created_at": datetime.now().isoformat(),
            }
            current_export_task_id = task_id
        
        # Start background export task
        thread = threading.Thread(
            target=_export_task,
            args=(
                task_id,
                papers_dir,
                export_options,
            ),
            daemon=True,
        )
        thread.start()
        
        return jsonify({
            "success": True,
            "task_id": task_id,
            "message": "Export task started"
        })
    
    @app.route("/api/export/status/<task_id>", methods=["GET"])
    def api_export_status(task_id: str):
        """Query export task status"""
        with export_tasks_lock:
            if task_id not in export_tasks:
                return jsonify({
                    "success": False,
                    "error": "Task does not exist"
                }), 404
            
            task = export_tasks[task_id]
            return jsonify({
                "success": True,
                "task": {
                    "task_id": task["task_id"],
                    "status": task["status"],
                    "progress": task["progress"],
                    "total": task["total"],
                    "current_paper": task["current_paper"],
                    "error": task["error"],
                    "created_at": task["created_at"],
                }
            })
    
    @app.route("/api/export/download/<task_id>", methods=["GET"])
    def api_export_download(task_id: str):
        """Download the exported ZIP document"""
        with export_tasks_lock:
            if task_id not in export_tasks:
                return jsonify({
                    "success": False,
                    "error": "Task does not exist"
                }), 404
            
            task = export_tasks[task_id]
            if task["status"] != "completed":
                return jsonify({
                    "success": False,
                    "error": "Export task not completed"
                }), 400
            
            zip_path = task.get("zip_path")
            if not zip_path or not os.path.exists(zip_path):
                return jsonify({
                    "success": False,
                    "error": "Export file does not exist"
                }), 404
        
        # Generate download file name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"PaperPilot_Export_{timestamp}.zip"
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=download_filename,
            mimetype="application/zip"
        )
    
    @app.route("/api/export/cancel/<task_id>", methods=["POST"])
    def api_export_cancel(task_id: str):
        """Cancel export task"""
        global current_export_task_id
        
        with export_tasks_lock:
            if task_id not in export_tasks:
                return jsonify({
                    "success": False,
                    "error": "Task does not exist"
                }), 404
            
            task = export_tasks[task_id]
            if task["status"] in ["completed", "failed", "cancelled"]:
                return jsonify({
                    "success": False,
                    "error": "The task has ended and cannot be canceled"
                }), 400
            
            # Mark as canceled
            task["status"] = "cancelled"
            task["error"] = "User cancels"
            
            if current_export_task_id == task_id:
                current_export_task_id = None
        
        return jsonify({
            "success": True,
            "message": "Export task canceled"
        })


def _export_task(
    task_id: str,
    papers_dir: str,
    export_options: Dict[str, Any],
):
    """Background export task (export only JSON metadata)"""
    global current_export_task_id
    
    def update_progress(progress: int, total: int, current_item: str):
        with export_tasks_lock:
            if task_id in export_tasks:
                export_tasks[task_id]["progress"] = progress
                export_tasks[task_id]["total"] = total
                export_tasks[task_id]["current_paper"] = current_item
    
    try:
        # Update status is running
        with export_tasks_lock:
            if task_id not in export_tasks:
                return
            export_tasks[task_id]["status"] = "running"
        
        print(f"[Export] Start export task: {task_id}")
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix="paper_export_")
        zip_path = os.path.join(temp_dir, "export.zip")
        
        try:
            # Export papers of folder JSON metadata
            print(f"[Export] Start packaging folder metadata: {papers_dir}")
            _export_papers_folder_to_zip(
                papers_dir,
                zip_path,
                progress_callback=update_progress,
            )
            
            print(f"[Export] Export completed: {zip_path}")
            
            # Update task status to complete
            with export_tasks_lock:
                if task_id in export_tasks:
                    export_tasks[task_id]["status"] = "completed"
                    export_tasks[task_id]["zip_path"] = zip_path
                    export_tasks[task_id]["current_paper"] = "Export completed"
        
        except Exception as e:
            print(f"[Export] Export failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Update task status is failed
            with export_tasks_lock:
                if task_id in export_tasks:
                    export_tasks[task_id]["status"] = "failed"
                    export_tasks[task_id]["error"] = str(e)
            
            # Clean temporary files
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    finally:
        # Clean up current tasksID
        with export_tasks_lock:
            if current_export_task_id == task_id:
                current_export_task_id = None
