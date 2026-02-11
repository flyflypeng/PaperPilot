"""
MinerU API Client
Provides integration with MinerU cloud API for PDF parsing
"""

import os
import shutil
import time
import zipfile
from typing import Callable, Dict, Optional

import requests


class MinerUAPIClient:
    """MinerU API client for PDF parsing via cloud API"""

    def __init__(self, token: str):
        """
        Initialize MinerU API client

        Args:
            token: API authentication token
        """
        self.token = token
        self.base_url = "https://mineru.net/api/v4"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def upload_and_parse(
        self, file_path: str, data_id: Optional[str] = None, model_version: str = "vlm"
    ) -> Optional[str]:
        """
        Upload file and request parsing

        Args:
            file_path: Path to PDF file
            data_id: Optional data ID for tracking
            model_version: Model version (default: vlm)

        Returns:
            batch_id if successful, None otherwise
        """
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return None

        file_name = os.path.basename(file_path)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Check file size limit (200MB)
        if file_size_mb > 200:
            print(f"File size exceeds limit (200MB): {file_size_mb:.2f} MB")
            return None

        # Step 1: Request upload URL
        url = f"{self.base_url}/file-urls/batch"
        data = {
            "files": [{"name": file_name, "data_id": data_id or file_name}],
            "model_version": model_version,
        }

        try:
            response = requests.post(url, headers=self.headers, json=data, timeout=30)

            if response.status_code != 200:
                print(f"Failed to request upload URL: HTTP {response.status_code}")
                print(f"Response: {response.text}")
                return None

            result = response.json()

            if result.get("code") != 0:
                print(f"API error: {result.get('msg')}")
                return None

            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]

            print(f"Got upload URL, batch_id: {batch_id}")

        except Exception as e:
            print(f"Failed to request upload URL: {e}")
            return None

        # Step 2: Upload file
        try:
            with open(file_path, "rb") as f:
                upload_response = requests.put(upload_url, data=f, timeout=300)

                if upload_response.status_code != 200:
                    print(f"File upload failed: HTTP {upload_response.status_code}")
                    return None

            print(f"File uploaded successfully")
            return batch_id

        except Exception as e:
            print(f"File upload failed: {e}")
            return None

    def get_batch_results(self, batch_id: str) -> Optional[Dict]:
        """
        Query batch parsing results

        Args:
            batch_id: Batch ID

        Returns:
            Result data or None
        """
        url = f"{self.base_url}/extract-results/batch/{batch_id}"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)

            if response.status_code != 200:
                print(f"Query failed: HTTP {response.status_code}")
                return None

            result = response.json()

            if result.get("code") != 0:
                print(f"API error: {result.get('msg')}")
                return None

            return result["data"]

        except Exception as e:
            print(f"Query failed: {e}")
            return None

    def wait_for_completion(
        self,
        batch_id: str,
        check_interval: int = 10,
        max_wait_time: int = 1800,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Optional[Dict]:
        """
        Wait for parsing to complete

        Args:
            batch_id: Batch ID
            check_interval: Check interval in seconds
            max_wait_time: Maximum wait time in seconds
            progress_callback: Progress callback function(state, extracted_pages, total_pages)

        Returns:
            Final result data or None
        """
        start_time = time.time()

        while True:
            # Check timeout
            elapsed_time = time.time() - start_time
            if elapsed_time > max_wait_time:
                print(f"Timeout: waited {elapsed_time:.0f} seconds")
                return None

            # Query results
            data = self.get_batch_results(batch_id)

            if not data:
                print(f"Query failed, retrying in {check_interval} seconds...")
                time.sleep(check_interval)
                continue

            extract_results = data.get("extract_result", [])

            if not extract_results:
                print(f"No results yet, retrying in {check_interval} seconds...")
                time.sleep(check_interval)
                continue

            # Check all file statuses
            for result in extract_results:
                file_name = result.get("file_name", "unknown")
                state = result.get("state", "unknown")

                if progress_callback:
                    if state == "running":
                        progress = result.get("extract_progress", {})
                        extracted = progress.get("extracted_pages", 0)
                        total = progress.get("total_pages", 0)
                        progress_callback(state, extracted, total)
                    else:
                        progress_callback(state, 0, 0)

                if state == "done":
                    print(f"File {file_name} parsing completed")
                elif state == "failed":
                    err_msg = result.get("err_msg", "Unknown error")
                    print(f"File {file_name} parsing failed: {err_msg}")

            # Check if all completed
            all_done = all(
                r.get("state") in ["done", "failed"] for r in extract_results
            )

            if all_done:
                print("All tasks completed")
                return data

            # Wait for next check
            time.sleep(check_interval)

    def download_and_extract_result(
        self, zip_url: str, extract_dir: str
    ) -> Optional[str]:
        """
        Download and extract result ZIP

        Args:
            zip_url: Result ZIP URL
            extract_dir: Extract directory

        Returns:
            Extracted directory path or None
        """
        try:
            # Create extract directory
            os.makedirs(extract_dir, exist_ok=True)

            # Download ZIP file
            zip_filename = os.path.join(extract_dir, "result.zip")
            print(f"Downloading result ZIP...")

            response = requests.get(zip_url, stream=True, timeout=300)

            if response.status_code != 200:
                print(f"Download failed: HTTP {response.status_code}")
                return None

            with open(zip_filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"Download completed, extracting...")

            # Extract ZIP
            with zipfile.ZipFile(zip_filename, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            # Delete ZIP file
            os.remove(zip_filename)

            print(f"Extraction completed: {extract_dir}")
            return extract_dir

        except Exception as e:
            print(f"Download/extraction failed: {e}")
            return None

    def parse_pdf_to_markdown(
        self,
        pdf_path: str,
        output_dir: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Optional[str]:
        """
        One-stop PDF parsing: upload -> wait -> download -> return Markdown path

        Args:
            pdf_path: PDF file path
            output_dir: Output directory (equivalent to outputs/xxx/vlm/)
            progress_callback: Progress callback function

        Returns:
            Markdown file path or None
        """
        try:
            # Step 1: Upload and parse
            print("Step 1: Uploading file and requesting parsing...")
            batch_id = self.upload_and_parse(pdf_path)

            if not batch_id:
                print("Upload failed")
                return None

            # Step 2: Wait for completion
            print("Step 2: Waiting for parsing to complete...")
            result_data = self.wait_for_completion(
                batch_id, check_interval=10, progress_callback=progress_callback
            )

            if not result_data:
                print("Parsing timeout or failed")
                return None

            # Step 3: Get result URL
            extract_results = result_data.get("extract_result", [])
            if not extract_results:
                print("No parsing results")
                return None

            first_result = extract_results[0]
            state = first_result.get("state")

            if state != "done":
                err_msg = first_result.get("err_msg", "Unknown error")
                print(f"Parsing failed: {err_msg}")
                return None

            zip_url = first_result.get("full_zip_url")
            if not zip_url:
                print("No result URL")
                return None

            # Step 4: Download and extract
            print("Step 3: Downloading and extracting results...")
            extract_dir = self.download_and_extract_result(zip_url, output_dir)

            if not extract_dir:
                print("Download/extraction failed")
                return None

            # Step 5: Find Markdown file and rename for consistency
            # API returns full.md, but local mode generates {filename}.md
            # Rename full.md to match local behavior
            pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
            full_md = os.path.join(output_dir, "full.md")
            target_md = os.path.join(output_dir, f"{pdf_basename}.md")

            if os.path.exists(full_md):
                shutil.move(full_md, target_md)
                print(f"Renamed full.md to {pdf_basename}.md")
            else:
                # Try to find any .md file
                md_files = [f for f in os.listdir(output_dir) if f.endswith(".md")]
                if md_files:
                    target_md = os.path.join(output_dir, md_files[0])
                else:
                    print("No Markdown file found in extracted results")
                    return None

            # Verify images directory exists
            images_dir = os.path.join(output_dir, "images")
            if os.path.exists(images_dir):
                print(f"Images directory found: {images_dir}")
            else:
                print("Warning: No images directory found")

            # Clean up unwanted files (keep only .md and images/)
            for item in os.listdir(output_dir):
                item_path = os.path.join(output_dir, item)
                if item == "images":
                    continue
                elif item.endswith(".md"):
                    continue
                else:
                    # Delete other files (layout.json, model.json, etc.)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        print(f"Removed directory: {item}")
                    else:
                        os.remove(item_path)
                        print(f"Removed file: {item}")

            print(f"PDF parsing completed, Markdown file: {target_md}")
            return target_md

        except Exception as e:
            print(f"PDF parsing failed: {e}")
            import traceback

            traceback.print_exc()
            return None
