"""
Daily arXiv Crawler module

Provided daily arXiv Paper acquisition function, support:
- Automated scheduled capture
- by date/Partition organization essay
- progress tracking
- Cleaning up expired papers
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import arxiv

from resophy.database.dao.paper_dao import PaperDAO
from resophy.database.dao.daily_arxiv_dao import DailyArxivDAO

# System prompt words extracted by the organization
AFFILIATION_EXTRACTION_PROMPT = """I will provide you with the first-page information of a paper. You need to extract all affiliations (institution names) from it and also extract the homepage and github repo url if there is. For affiliations, do not include author names. If an affiliation includes details such as region, department, school, or college, those should be omitted. Only keep the main institution name (e.g., School of Computer Science, Fudan University → Fudan University).

Output the result directly in JSON format, and make sure it is valid JSON. For example:
{"affiliations": ["Google Brain", "Google Research", "Fudan University"], "homepage": "transformer.github.io", "github": "github.com/transformer"}

Notes:
1. If there is no homepage or github url, use the JSON value null (not the string "null" and not Python None).
2. Do NOT add a trailing comma after the last field.
3. Do not include any explanation or extra text, only output the JSON object.

Now the input is:
"""

# System prompt words for summary summary and keyword extraction
SUMMARY_EXTRACTION_PROMPT = """I will give you one AI English abstract of the article. You need to briefly summarize what problem this article solves and how it solves it, and then provide some information about the article at the end. type of article 3indivual English keywords, this type does not need to be subdivided, but should be divided into major categories, such as Image Generation，Object Detection，3D Reconstruction This kind is as follows JSON format output:

{"summary": "This article mainly solves...problem. The author proposes...method, through...Realized...", "keywords": ["Keyword1", "Keyword2", "Keyword3"]}

Notice:
1. summary Use Chinese concise description, control within 100-200 Character
2. keywords In English, provided 3 keywords that best represent the type of article
3. direct output JSON, without any other explanation

The summary entered now is:
"""


def _normalize_keyword_match_text(text: str) -> str:
    if not text:
        return ""
    text = text.casefold()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_any_keyword_in_title_or_abstract(
    title: str, abstract: str, keyword_list: List[str]
) -> List[str]:
    if not keyword_list:
        return []
    haystack = _normalize_keyword_match_text(f"{title or ''} {abstract or ''}")
    if not haystack:
        return []
    matched = []
    for kw in keyword_list:
        kw_norm = _normalize_keyword_match_text(kw)
        if not kw_norm:
            continue
        if kw_norm in haystack:
            matched.append(kw)
    return matched



def get_arxiv_announce_date(submitted: datetime = None) -> datetime:
    """

    arXiv Publication time rules:
    - Eastern Time 14:00(Monday to Friday) One day before announcement 14:00 UTC Previously submitted papers
    - No publication will be made on weekends. Papers submitted on Friday will be published on the following Monday.

    Time zone conversion:
    - Daylight Saving Time (3second sunday of month - 11Error 500 (Server Error)!!1500.That’s an error.There was an error. Please try again later.That’s all we know. 14:00 = UTC 18:00 = The next day Beijing time 02:00
    - Winter Time (other times): Eastern Time 14:00 = UTC 19:00 = The next day Beijing time 03:00

    Attribution of the paper in Beijing Time:
    - Daylight Saving Time: the day before UTC 18:00 Until the same day UTC 18:00 Papers submitted during the period will be attributed to the same day Beijing time
    - Winter time: the day before UTC 19:00 Until the same day UTC 19:00 Papers submitted during the period will be attributed to the same day Beijing time

    Args:
        submitted: Paper submission time (UTC), if None then use the current time

    Returns:
        The paper is in arXiv Announcement date (Beijing time and date)
    """
    if submitted is None:
        submitted = datetime.utcnow()

    # If the incoming time is with time zone (offset-aware), converted to UTC naive datetime
    if submitted.tzinfo is not None:
        submitted = submitted.replace(tzinfo=None)

    # Determine whether it is daylight saving time (Eastern Time)
    # Daylight Saving Time:3second sunday of month 02:00 arrive 11first sunday of month 02:00
    def is_dst(dt):
        """judge given UTC Whether the corresponding US Eastern Time is Daylight Saving Time"""
        year = dt.year
        # 3second sunday of month
        march = datetime(year, 3, 1)
        dst_start = march + timedelta(days=(13 - march.weekday()) % 7)
        while dst_start.day < 8:
            dst_start += timedelta(days=7)
        # 11first sunday of month
        november = datetime(year, 11, 1)
        dst_end = november + timedelta(days=(6 - november.weekday()) % 7)
        return dst_start <= dt < dst_end

    # determined release time UTC hours (daylight saving time 18:00, winter time 19:00）
    publish_hour = 18 if is_dst(submitted) else 19

    # arXiv Release logic (based on Beijing time):
    # the day before publish_hour Until the same day publish_hour Papers submitted during the period will be published on the corresponding Beijing time and date at the end of the publishing window.
    #
    # For example: winter time (publish_hour = 19）
    #   12moon2day 19:00 UTC arrive 12moon3day 19:00 UTC papers submitted between
    #   Window end time:12moon3day 19:00 UTC = Beijing time 12moon4day 03:00
    #   → Attribution to Beijing time 12moon4day
    #
    # Another example: Daylight Saving Time (publish_hour = 18）
    #   5moon2day 18:00 UTC arrive 5moon3day 18:00 UTC papers submitted between
    #   Window end time:5moon3day 18:00 UTC = Beijing time 5moon4day 02:00
    #   → Attribution to Beijing time 5moon4day

    # Calculate the Beijing time and date corresponding to the end time of the release window
    utc_date = submitted.date()

    if submitted.hour >= publish_hour:
        # Submission time is after the publishing time of the day
        # The release window ends: the next day publish_hour
        # For example:12moon2day 20:00 UTC → The window end time is 12moon3day 19:00 UTC
        window_end_utc = datetime.combine(
            utc_date + timedelta(days=1), datetime.min.time()
        ) + timedelta(hours=publish_hour)
    else:
        # Submission time is before the publishing time of the day
        # The publishing window end time is: today's publish_hour
        # For example:12moon2day 10:00 UTC → The window end time is 12moon2day 19:00 UTC
        window_end_utc = datetime.combine(utc_date, datetime.min.time()) + timedelta(
            hours=publish_hour
        )

    # Convert the window end time to Beijing time and get the paper attribution date
    window_end_beijing = window_end_utc + timedelta(hours=8)
    announce_date = window_end_beijing.date()

    # Adjustment to weekends: Saturday and Sunday papers postponed to Monday
    weekday = announce_date.weekday()
    if weekday == 5:  # Saturday -> Monday
        announce_date = announce_date + timedelta(days=2)
    elif weekday == 6:  # Sunday -> Monday
        announce_date = announce_date + timedelta(days=1)

    return datetime.combine(announce_date, datetime.min.time())


def get_today_arxiv_date() -> str:
    """
    Get today's date string (YYYY-MM-DD)
    Use local time
    """
    return datetime.now().strftime("%Y-%m-%d")


@dataclass
class ArxivPaper:
    """arXiv Paper data class"""

    arxiv_id: str
    title: str
    authors: str
    abstract: str
    published: datetime  # First submission time
    updated: datetime  # Latest version time
    announced: datetime  # Publication date (in arXiv date displayed in the list)
    pdf_url: str
    categories: List[str]
    primary_category: str
    comment: Optional[str] = None
    journal_ref: Optional[str] = None

    # local status
    local_pdf_path: Optional[str] = None
    thumbnail_path: Optional[str] = None

    # Institutional information
    affiliations: List[str] = field(default_factory=list)
    countries: List[str] = field(
        default_factory=list
    )  # list of countries, with affiliations correspond
    affiliations_extracted: bool = False

    # Project link
    homepage: Optional[str] = None
    github: Optional[str] = None

    # LLM Extracted abstracts and keywords
    summary: Optional[str] = None  # Brief summary in Chinese
    keywords: List[str] = field(default_factory=list)  # English keywords
    summary_extracted: bool = False

    matched_keywords: List[str] = field(default_factory=list)

    # Grab information
    fetch_category: Optional[str] = None  # Which partition was grabbed from?
    fetch_date: Optional[str] = None  # Fetch date (YYYY-MM-DD)

    # PDF Download status
    pdf_downloaded: bool = False  # PDF Has the download been successful?

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "published": self.published.isoformat() if self.published else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "announced": self.announced.isoformat() if self.announced else None,
            "pdf_url": self.pdf_url,
            "categories": self.categories,
            "primary_category": self.primary_category,
            "comment": self.comment,
            "journal_ref": self.journal_ref,
            "local_pdf_path": self.local_pdf_path,
            "thumbnail_path": self.thumbnail_path,
            "affiliations": self.affiliations,
            "countries": self.countries,
            "affiliations_extracted": self.affiliations_extracted,
            "homepage": self.homepage,
            "github": self.github,
            "summary": self.summary,
            "keywords": self.keywords,
            "summary_extracted": self.summary_extracted,
            "matched_keywords": self.matched_keywords,
            "fetch_category": self.fetch_category,
            "fetch_date": self.fetch_date,
            "pdf_downloaded": self.pdf_downloaded,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArxivPaper":
        """Create from dictionary"""

        def parse_datetime(s):
            if not s:
                return None
            if isinstance(s, datetime):
                return s
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except:
                return None

        return cls(
            arxiv_id=data.get("arxiv_id", ""),
            title=data.get("title", ""),
            authors=data.get("authors", ""),
            abstract=data.get("abstract", ""),
            published=parse_datetime(data.get("published")),
            updated=parse_datetime(data.get("updated")),
            announced=parse_datetime(data.get("announced")),
            pdf_url=data.get("pdf_url", ""),
            categories=data.get("categories", []),
            primary_category=data.get("primary_category", ""),
            comment=data.get("comment"),
            journal_ref=data.get("journal_ref"),
            local_pdf_path=data.get("local_pdf_path"),
            thumbnail_path=data.get("thumbnail_path"),
            affiliations=data.get("affiliations", []),
            countries=data.get("countries", []),
            affiliations_extracted=data.get("affiliations_extracted", False),
            homepage=data.get("homepage"),
            github=data.get("github"),
            summary=data.get("summary"),
            keywords=data.get("keywords", []),
            summary_extracted=data.get("summary_extracted", False),
            matched_keywords=data.get("matched_keywords", []),
            fetch_category=data.get("fetch_category"),
            fetch_date=data.get("fetch_date"),
            pdf_downloaded=data.get("pdf_downloaded", False),
        )

    @classmethod
    def from_arxiv_result(
        cls, result: arxiv.Result, fetch_category: str = None
    ) -> "ArxivPaper":
        """from arxiv library Result Object creation"""
        # extract arXiv ID
        arxiv_id = result.entry_id.split("/abs/")[-1]

        # Format author
        authors = ", ".join(author.name for author in result.authors)

        # Get category
        categories = list(result.categories) if result.categories else []
        primary_category = result.primary_category or (
            categories[0] if categories else ""
        )

        # Calculate publication date
        announced = get_arxiv_announce_date(result.published)

        return cls(
            arxiv_id=arxiv_id,
            title=result.title.replace("\n", " ").strip(),
            authors=authors,
            abstract=(
                result.summary.replace("\n", " ").strip() if result.summary else ""
            ),
            published=result.published,
            updated=result.updated,
            announced=announced,
            pdf_url=result.pdf_url,
            categories=categories,
            primary_category=primary_category,
            comment=result.comment,
            journal_ref=result.journal_ref,
            fetch_category=fetch_category,
            fetch_date=get_today_arxiv_date(),
        )


class FetchProgress:
    """Crawl progress tracking"""

    def __init__(self):
        self.total = 0
        self.current = 0
        self.status = "idle"  # idle, fetching, processing, done, error
        self.message = ""
        self.current_paper = None
        self.current_paper_start_time = (
            None  # The timestamp when the current paper started processing
        )
        self.current_paper_pdf_path = None  # Currently downloading PDF file path
        self.papers = []
        self.lock = threading.Lock()

    def reset(self, total: int = 0):
        with self.lock:
            self.total = total
            self.current = 0
            self.status = "fetching"
            self.message = "Retrieving paper list..."
            self.current_paper = None
            self.current_paper_start_time = None
            self.current_paper_pdf_path = None
            self.papers = []

    def set_processing(self, total: int):
        with self.lock:
            self.total = total
            self.current = 0
            self.status = "processing"
            self.message = f"Processing 0/{total} papers"
            self.current_paper_start_time = None
            self.current_paper_pdf_path = None

    def update(self, current: int, paper_title: str = None, pdf_path: str = None):
        with self.lock:
            self.current = current
            # If the paper title changes, record the new start time
            if paper_title and paper_title != self.current_paper:
                self.current_paper = paper_title
                self.current_paper_start_time = time.time()
                self.current_paper_pdf_path = pdf_path  # set up PDF path
            elif not paper_title:
                self.current_paper = None
                self.current_paper_start_time = None
                self.current_paper_pdf_path = None
            # If only update PDF Path (during download), updated even if the title is the same
            if pdf_path and self.current_paper:
                self.current_paper_pdf_path = pdf_path
            self.message = f"Processing {current}/{self.total} papers"

    def add_paper(self, paper_dict: Dict):
        with self.lock:
            self.papers.append(paper_dict)

    def set_done(self, message: str = "Finish"):
        with self.lock:
            self.status = "done"
            self.message = message
            self.current_paper = None
            self.current_paper_start_time = None
            self.current_paper_pdf_path = None

    def set_error(self, error: str):
        with self.lock:
            self.status = "error"
            self.message = error
            self.current_paper = None
            self.current_paper_start_time = None
            self.current_paper_pdf_path = None

    def to_dict(self) -> Dict:
        with self.lock:
            # Calculate the elapsed time of the current paper (seconds)
            elapsed_seconds = 0
            if self.current_paper_start_time:
                elapsed_seconds = int(time.time() - self.current_paper_start_time)

            # Calculate the currently downloaded PDF File size (bytes)
            current_paper_pdf_size = 0
            if self.current_paper_pdf_path and os.path.exists(
                self.current_paper_pdf_path
            ):
                try:
                    current_paper_pdf_size = os.path.getsize(
                        self.current_paper_pdf_path
                    )
                except:
                    pass

            return {
                "total": self.total,
                "current": self.current,
                "status": self.status,
                "message": self.message,
                "current_paper": self.current_paper,
                "current_paper_elapsed_seconds": elapsed_seconds,  # Current paper elapsed time (seconds)
                "current_paper_pdf_size": current_paper_pdf_size,  # currently downloaded PDF File size (bytes)
                "papers": list(self.papers),
            }


class DailyArxivManager:
    """
    Daily arXiv Manager

    Responsible:
    - by date/Organize thesis files into partitions
    - Automated scheduled capture
    - progress tracking
    - Cleaning up expired papers
    """

    def __init__(self, base_dir: str, settings_file: str):
        """
        initialization

        Args:
            base_dir: Basic directory, such as papers/.daily_arxiv_temp
            settings_file: Set file path
        """
        self.base_dir = base_dir
        self.settings_file = settings_file

        os.makedirs(base_dir, exist_ok=True)

        # arXiv client
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3.0,
            num_retries=3,
        )

        # Progress tracking (by partition)
        self.progress: Dict[str, FetchProgress] = {}

        # scheduler
        self._scheduler_thread = None
        self._scheduler_running = False
        self._last_fetch_time: Dict[str, datetime] = {}

        # LLM Configure callback
        self._get_llm_config: Optional[Callable[[], Dict]] = None

        # User settings callback (for getting aiLanguage)
        self._get_user_settings: Optional[Callable[[], Dict]] = None

        # LLM API Status tracking (for front-end display)
        self._llm_api_failed: bool = False
        self._llm_api_error_message: str = ""

    def set_llm_config_callback(self, callback: Callable[[], Dict]):
        """set get LLM Configured callback function"""
        self._get_llm_config = callback

    def set_user_settings_callback(self, callback: Callable[[], Dict]):
        """set get user settings callback function (for getting aiLanguage)"""
        self._get_user_settings = callback

    def get_settings(self) -> Dict:
        """Get settings"""
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def get_date_dir(self, date_str: str) -> str:
        """Get date directory path"""
        return os.path.join(self.base_dir, date_str)

    def get_category_dir(self, date_str: str, category: str) -> str:
        """Get partition directory path"""
        return os.path.join(self.base_dir, date_str, category.replace(".", "_"))

    def get_available_dates(self) -> List[str]:
        """
        Get a list of dates with papers

        Returns:
            List of dates (descending order, newest first)
        """
        return PaperDAO.get_available_daily_dates()

    def get_papers_for_date(self, date_str: str, category: str = None) -> List[Dict]:
        """
        Get papers of a certain date

        Args:
            date_str: date string (YYYY-MM-DD)
            category: Partition (optional, if not specified, all partitions will be returned)

        Returns:
            Thesis dictionary list
        """
        papers = PaperDAO.get_daily_papers(date_str, category)

        settings = self.get_settings()
        keyword_list = settings.get("keywordList", []) or []
        keyword_list = [k for k in keyword_list if isinstance(k, str) and k.strip()]

        result_papers = []
        for paper_data in papers:
            # Check if PDF exists
            local_pdf_path = paper_data.get("file_path")
            if local_pdf_path and not os.path.exists(local_pdf_path):
                continue

            paper_data['local_pdf_path'] = local_pdf_path
            paper_data['pdf_downloaded'] = True

            if keyword_list:
                matched = match_any_keyword_in_title_or_abstract(
                    paper_data.get("title", ""),
                    paper_data.get("abstract", ""),
                    keyword_list,
                )
                if not matched:
                    continue
                paper_data["matched_keywords"] = matched

            result_papers.append(paper_data)

        return result_papers

    def get_progress(self, category: str) -> Dict:
        """Get the crawling progress of a partition"""
        if category not in self.progress:
            self.progress[category] = FetchProgress()
        return self.progress[category].to_dict()

    def fetch_papers(
        self,
        category: str,
        date_str: str = None,
        force: bool = False,
    ) -> List[Dict]:
        """
        Fetch papers (automatically fetch all papers today)

        Args:
            category: arXiv Partition
            date_str: Target date (default today), only crawl papers on this date
            force: Force re-crawl

        Returns:
            Paper list (stored by the actual publication date of the paper)
        """
        if date_str is None:
            date_str = get_today_arxiv_date()

        # Initialization progress
        if category not in self.progress:
            self.progress[category] = FetchProgress()
        progress = self.progress[category]
        progress.reset(0)  # The total number is unknown, will be updated later

        try:
            # Get papers until you find papers before today's date
            print(
                f"[DailyArxiv] Getting {category} Partition {date_str} All papers of..."
            )

            settings = self.get_settings()
            keyword_list = settings.get("keywordList", []) or []
            keyword_list = [k for k in keyword_list if isinstance(k, str) and k.strip()]

            # Get enough papers at once (up to 500 articles) and then filter for papers with target date
            max_fetch = 500
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=max_fetch,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            all_results = []
            checked_count = 0
            consecutive_older_count = (
                0  # Number of papers with earlier dates found consecutively
            )
            min_check_count = 100  # Minimum number of papers examined
            max_consecutive_older = 20  # Maximum number of older papers found consecutively, stopping if exceeded
            matched_keywords_by_arxiv_id: Dict[str, List[str]] = {}

            for result in self.client.results(search):
                checked_count += 1

                # Check paper date
                paper_tmp = ArxivPaper.from_arxiv_result(
                    result, fetch_category=category
                )
                paper_date = paper_tmp.announced.date() if paper_tmp.announced else None

                if paper_date and paper_date == target_date:
                    matched_keywords = (
                        match_any_keyword_in_title_or_abstract(
                            paper_tmp.title, paper_tmp.abstract, keyword_list
                        )
                        if keyword_list
                        else []
                    )
                    if keyword_list and not matched_keywords:
                        continue
                    all_results.append(result)
                    if matched_keywords:
                        matched_keywords_by_arxiv_id[paper_tmp.arxiv_id] = matched_keywords
                    consecutive_older_count = 0  # Reset consecutive earlier date count
                elif paper_date and paper_date < target_date:
                    # Papers older than target date found
                    consecutive_older_count += 1
                    # Only stop when at least a certain number of papers have been examined and multiple papers of earlier dates are found in a row
                    if (
                        checked_count >= min_check_count
                        and consecutive_older_count >= max_consecutive_older
                    ):
                        print(
                            f"[DailyArxiv] checked {checked_count} papers, found consecutively {consecutive_older_count} an earlier paper ({paper_date} < {target_date}), stop crawling"
                        )
                        break
                # If it's a paper with a future date, skip it (usually it won't show up)

                # Periodically output progress
                if checked_count % 50 == 0:
                    print(
                        f"[DailyArxiv] checked {checked_count} papers, found {len(all_results)} target date papers"
                    )

            results = all_results
            print(
                f"[DailyArxiv] checked {checked_count} papers, found {len(results)} Chapter {date_str} of {category} paper"
            )

            if not results:
                progress.set_done("No matching papers found")
                return []

            # First, count the actual publication date distribution of papers.
            date_counts = {}
            for result in results:
                paper_tmp = ArxivPaper.from_arxiv_result(
                    result, fetch_category=category
                )
                announce_date = (
                    paper_tmp.announced.strftime("%Y-%m-%d")
                    if paper_tmp.announced
                    else "unknown"
                )
                date_counts[announce_date] = date_counts.get(announce_date, 0) + 1

            # Print date distribution
            date_info = ", ".join(
                [
                    f"{d}: {c}Chapter"
                    for d, c in sorted(date_counts.items(), reverse=True)
                ]
            )
            print(f"[DailyArxiv] Distribution of paper publication dates: {date_info}")

            # Set processing progress
            progress.set_processing(len(results))

            # get LLM Configuration
            llm_config = {}
            if self._get_llm_config:
                llm_config = self._get_llm_config()

            # Get custom prompt
            affiliation_prompt = settings.get("affiliationPrompt")
            max_keywords = settings.get("maxKeywords", 1)

            # Get user language preference (default to Chinese for backward compatibility)
            ai_language = "zh"
            if self._get_user_settings:
                try:
                    user_settings = self._get_user_settings()
                    ai_language = user_settings.get("aiLanguage", "zh")
                except Exception as e:
                    print(f"[DailyArxiv] Failed to get user settings: {e}")

            # Select summary prompt based on user language
            summary_prompt = None
            if ai_language and ai_language.lower().startswith("zh"):
                summary_prompt = settings.get("summaryPromptZh")
            else:
                summary_prompt = settings.get("summaryPromptEn")

            # If no language-specific prompt found, fall back to default
            if not summary_prompt:
                # Use built-in default prompt based on language
                if ai_language and ai_language.lower().startswith("zh"):
                    # Chinese default prompt
                    summary_prompt = """我会给你一篇 AI 文章的英文摘要，以及一个可选关键词列表（英文）。你需要：

用中文简要总结这篇文章在解决什么问题、如何解决的，字数控制在 100-200 字。

从我提供的关键词列表中挑选最能代表文章类型的关键词（英文）

按如下 JSON 格式输出结果：

{"summary": "这篇文章主要解决...的问题。作者提出...方法，通过...实现了...", "keywords": ["Keyword"]}

注意

summary 必须中文，简洁、客观。

keywords 必须来自我提供的关键词列表：[{keyword_list}], 最多{max_keywords}个关键词。一定要是符合这篇文章的关键词，不能随意猜测。

直接输出 JSON，不要有其他解释。

现在输入的摘要是：
"""
                else:
                    # English default prompt
                    summary_prompt = """I will give you an English abstract of an AI paper, and an optional keyword list (in English). You need to:

Briefly summarize in English what problem this paper solves and how it solves it, keep it within 100-200 words.

Select keywords (in English) from the keyword list I provide that best represent the type of paper.

Output the result in the following JSON format:

{"summary": "This paper mainly solves...problem. The authors propose...method, through...achieved...", "keywords": ["Keyword"]}

Notes:

summary must be in English, concise and objective.

keywords must come from the keyword list I provide: [{keyword_list}], at most {max_keywords} keywords. They must be keywords that match this paper, do not guess randomly.

Output JSON directly, no other explanations.

Now the input abstract is:
"""

            # Insert the keyword list and maximum number of keywords into prompt middle
            if summary_prompt:
                if keyword_list:
                    keyword_list_str = ", ".join(keyword_list)
                    summary_prompt = summary_prompt.replace(
                        "{keyword_list}", keyword_list_str
                    )
                # Replace the maximum number of keywords placeholder
                summary_prompt = summary_prompt.replace(
                    "{max_keywords}", str(max_keywords)
                )

            papers = []
            skipped_count = 0

            print(f"[DailyArxiv] Start processing {len(results)} papers...")
            for i, result in enumerate(results):
                try:
                    print(
                        f"[DailyArxiv] processing section {i+1}/{len(results)} papers..."
                    )
                    paper = ArxivPaper.from_arxiv_result(
                        result, fetch_category=category
                    )
                    if paper.arxiv_id in matched_keywords_by_arxiv_id:
                        paper.matched_keywords = matched_keywords_by_arxiv_id[paper.arxiv_id]
                    elif keyword_list:
                        paper.matched_keywords = match_any_keyword_in_title_or_abstract(
                            paper.title, paper.abstract, keyword_list
                        )

                    # Use the actual publication date of the paper as the storage directory
                    paper_announce_date = (
                        paper.announced.strftime("%Y-%m-%d")
                        if paper.announced
                        else date_str
                    )
                    paper.fetch_date = paper_announce_date

                    # Get the directory corresponding to the date
                    paper_cat_dir = self.get_category_dir(paper_announce_date, category)
                    os.makedirs(paper_cat_dir, exist_ok=True)

                    # Check if the paper exists in DB and has been downloaded
                    safe_id = paper.arxiv_id.replace("/", "_").replace(":", "_")
                    pdf_path = os.path.join(paper_cat_dir, f"{safe_id}.pdf")
                    
                    # Check DB
                    existing_paper_dict = PaperDAO.get_paper_by_arxiv_id(paper.arxiv_id)
                    # Also need to check if it's a daily paper (though arxiv_id is unique)
                    # And check if file exists
                    
                    if (
                        not force
                        and existing_paper_dict
                        and existing_paper_dict.get('is_daily')
                        and existing_paper_dict.get('file_path')
                        and os.path.exists(existing_paper_dict['file_path'])
                    ):
                        # Already exists and downloaded
                        
                        # Check thumbnails
                        if not existing_paper_dict.get('thumbnail_path'):
                             thumbnail_path = self._generate_thumbnail(
                                existing_paper_dict['file_path'], paper_cat_dir
                             )
                             if thumbnail_path:
                                 # Update DB
                                 existing_paper_dict['thumbnail_path'] = thumbnail_path
                                 # We need to save it back. 
                                 # But _save_paper takes dict from ArxivPaper.to_dict().
                                 # existing_paper_dict is from PaperDAO._row_to_dict().
                                 # They have different structures.
                                 # Let's manually update PaperDAO.
                                 PaperDAO.save_paper(existing_paper_dict)

                        skipped_count += 1
                        progress.update(
                            i + 1, f"[Already exists] {paper.title[:40]}"
                        )
                        print(
                            f"[DailyArxiv] Skip fully downloaded papers: {paper.arxiv_id}"
                        )
                        continue

                    # Update progress (update before starting the download so the frontend can see the current paper immediately)
                    # Set up first PDF Path (even if the file doesn't exist yet so the frontend can display it)
                    progress.update(i + 1, paper.title[:50], pdf_path=pdf_path)

                    # download PDF to the correct date directory (file size is updated periodically during download)
                    pdf_path = self._download_pdf(paper, paper_cat_dir, progress)
                    if pdf_path:
                        paper.local_pdf_path = pdf_path
                        paper.pdf_downloaded = True  # mark PDF Successfully downloaded

                        # Generate thumbnails (PDFFirst half of the first page)
                        thumbnail_path = self._generate_thumbnail(
                            pdf_path, paper_cat_dir
                        )
                        if thumbnail_path:
                            paper.thumbnail_path = thumbnail_path

                        # extraction mechanism,homepage and github(from PDF First page)
                        if (
                            llm_config.get("llmBaseUrl")
                            and llm_config.get("llmApiKey")
                            and llm_config.get("llmModel")
                        ):
                            extraction_result = self._extract_affiliations(
                                pdf_path,
                                llm_config["llmBaseUrl"],
                                llm_config["llmApiKey"],
                                llm_config["llmModel"],
                                prompt=affiliation_prompt,
                            )
                            paper.affiliations = extraction_result.get(
                                "affiliations", []
                            )
                            paper.countries = extraction_result.get("countries", [])
                            paper.homepage = extraction_result.get("homepage")
                            paper.github = extraction_result.get("github")
                            paper.affiliations_extracted = True
                    else:
                        # PDF Download failed
                        paper.pdf_downloaded = False
                        print(
                            f"[DailyArxiv] PDF Download failed, will try again at next check: {paper.arxiv_id}"
                        )

                    # Extract abstracts and keywords (from abstract）
                    # NOTE: Even if PDF Download failed, you can also extract abstracts and keywords
                    if (
                        llm_config.get("llmBaseUrl")
                        and llm_config.get("llmApiKey")
                        and llm_config.get("llmModel")
                        and paper.abstract
                    ):
                        summary_result = extract_summary_and_keywords_with_llm(
                            paper.abstract,
                            llm_config["llmBaseUrl"],
                            llm_config["llmApiKey"],
                            llm_config["llmModel"],
                            prompt=summary_prompt,
                        )
                        paper.summary = summary_result.get("summary")
                        paper.keywords = summary_result.get("keywords", [])
                        paper.summary_extracted = True

                    # Save paper metadata to DB
                    # even though PDF If the download fails, the metadata is also saved so that you can try again next time.
                    paper_dict = paper.to_dict()
                    self._save_paper(paper_dict, paper_cat_dir)

                    papers.append(paper_dict)
                    progress.add_paper(paper_dict)
                    print(
                        f"[DailyArxiv] Complete processing {i+1}/{len(results)} papers: {paper.arxiv_id}"
                    )

                except Exception as e:
                    # Capture exceptions when processing a single paper to avoid affecting subsequent papers
                    print(
                        f"[DailyArxiv] processing section {i+1}/{len(results)} An error occurred while writing the paper: {e}"
                    )
                    print(
                        f"[DailyArxiv] paper ID: {result.entry_id if hasattr(result, 'entry_id') else 'unknown'}"
                    )
                    import traceback

                    traceback.print_exc()
                    # Move on to the next paper
                    continue

            msg = f"Completed, added {len(papers)} papers"
            if skipped_count > 0:
                msg += f",jump over {skipped_count} Article already exists"
            progress.set_done(msg)
            self._last_fetch_time[category] = datetime.now()

            return papers

        except Exception as e:
            print(f"[DailyArxiv] crawl {category} Thesis failed: {e}")
            import traceback

            traceback.print_exc()
            progress.set_error(str(e))
            return []

    def _validate_pdf_integrity(self, pdf_path: str) -> bool:
        """verify PDF file integrity

        Returns:
            True if PDF The document is complete and valid,False otherwise
        """
        try:
            if not os.path.exists(pdf_path):
                return False

            file_size = os.path.getsize(pdf_path)
            if file_size == 0 or file_size < 1024:
                return False

            # examine PDF File header (must end with %PDF- beginning)
            with open(pdf_path, "rb") as f:
                header = f.read(8)
                if not header.startswith(b"%PDF-"):
                    print(f"[DailyArxiv] PDF Invalid file header: {pdf_path}")
                    return False

            # examine PDF End of file (should contain %%EOF）
            with open(pdf_path, "rb") as f:
                f.seek(max(0, file_size - 1024))  # read last1KB
                tail = f.read()
                if b"%%EOF" not in tail:
                    print(
                        f"[DailyArxiv] PDF Invalid end of file (missing %%EOF）: {pdf_path}"
                    )
                    return False

            # Try using PyMuPDF Open file to verify integrity (most reliable method)
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(pdf_path)
                # Try accessing the first and last pages
                if len(doc) == 0:
                    doc.close()
                    print(f"[DailyArxiv] PDF File has no pages: {pdf_path}")
                    return False
                # Try rendering the first page (verify file integrity)
                try:
                    page = doc[0]
                    _ = page.get_pixmap()  # Try rendering the page
                except Exception as e:
                    doc.close()
                    print(
                        f"[DailyArxiv] PDF File cannot render page: {pdf_path}, mistake: {e}"
                    )
                    return False
                doc.close()
            except ImportError:
                # if not PyMuPDF, try using PyPDF2
                try:
                    import PyPDF2

                    with open(pdf_path, "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        if len(pdf_reader.pages) == 0:
                            print(
                                f"[DailyArxiv] PDF File has no pages (PyPDF2): {pdf_path}"
                            )
                            return False
                        # Try to access the first page
                        _ = pdf_reader.pages[0]
                except Exception as e:
                    print(
                        f"[DailyArxiv] PDF File cannot be parsed (PyPDF2): {pdf_path}, mistake: {e}"
                    )
                    return False
            except Exception as e:
                print(
                    f"[DailyArxiv] PDF File verification failed: {pdf_path}, mistake: {e}"
                )
                return False

            return True
        except Exception as e:
            print(f"[DailyArxiv] verify PDF Integrity error: {pdf_path}, mistake: {e}")
            return False

    def _download_pdf(
        self, paper: ArxivPaper, cat_dir: str, progress: FetchProgress = None
    ) -> Optional[str]:
        """download PDF

        use export.arxiv.org to avoid IP Limitation issue

        Args:
            paper: Thesis object
            cat_dir: Categories
            progress: Progress tracking object (optional) used to update the file size during the download process
        """
        try:
            safe_id = paper.arxiv_id.replace("/", "_").replace(":", "_")
            pdf_filename = f"{safe_id}.pdf"
            pdf_path = os.path.join(cat_dir, pdf_filename)

            # If the file already exists, delete it (because it has been marked downloading, indicating that the previous download was not completed)
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                    print(
                        f"[DailyArxiv] Delete existing PDF file, re-download: {paper.arxiv_id}"
                    )
                except:
                    pass

            print(f"[DailyArxiv] download PDF: {paper.arxiv_id}")

            # Will PDF URL from arxiv.org Convert to export.arxiv.org(Officially recommended export service)
            # For example: https://arxiv.org/pdf/2512.04025v1 -> https://export.arxiv.org/pdf/2512.04025v1
            pdf_url = paper.pdf_url
            if "arxiv.org/pdf/" in pdf_url:
                pdf_url = pdf_url.replace("arxiv.org/pdf/", "export.arxiv.org/pdf/")
            elif "arxiv.org/abs/" in pdf_url:
                # in the case of abs URL, also converted to export
                pdf_url = pdf_url.replace("arxiv.org/abs/", "export.arxiv.org/pdf/")
            else:
                # if it is already export.arxiv.org, remain unchanged
                pass

            # Try using it first requests library (if available), which usually handles the anti-crawling mechanism better
            try:
                import requests

                # use requests Library, add complete browser request headers
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Referer": "https://arxiv.org/",
                    "Connection": "keep-alive",
                }

                # download PDF(use export.arxiv.org, no need to visit the home page first)
                response = requests.get(
                    pdf_url,
                    headers=headers,
                    timeout=30,
                    stream=True,
                    allow_redirects=True,
                )

                if response.status_code == 200:
                    chunk_count = 0
                    with open(pdf_path, "wb") as out_file:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                out_file.write(chunk)
                                chunk_count += 1
                                # every write 10 indivual chunk(about 80KB) Update the progress once
                                if progress and chunk_count % 10 == 0:
                                    progress.update(
                                        progress.current,
                                        progress.current_paper,
                                        pdf_path=pdf_path,
                                    )

                    # Check if the file downloaded successfully (basic check: the file exists and is not empty)
                    if os.path.exists(pdf_path):
                        file_size = os.path.getsize(pdf_path)
                        if (
                            file_size == 0 or file_size < 1024
                        ):  # less than1KBPossibly an error page
                            print(
                                f"[DailyArxiv] PDF File is empty or too small ({file_size} bytes),delete: {paper.arxiv_id}"
                            )
                            try:
                                os.remove(pdf_path)
                            except:
                                pass
                            return None

                    # Update the progress one last time to make sure the final file size is shown
                    if progress:
                        progress.update(
                            progress.current, progress.current_paper, pdf_path=pdf_path
                        )

                    print(f"[DailyArxiv] PDF Download successful: {paper.arxiv_id}")
                    return pdf_path
                else:
                    raise Exception(f"HTTP {response.status_code}: {response.reason}")

            except ImportError:
                # if not requests library, fallback to urllib
                # Create request, add User-Agent
                req = urllib.request.Request(
                    pdf_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "application/pdf,text/html,*/*",
                        "Referer": "https://arxiv.org/",
                    },
                )

                # Download file (urllib It is a one-time read and the progress cannot be updated during the download process)
                with urllib.request.urlopen(req, timeout=30) as response:
                    with open(pdf_path, "wb") as out_file:
                        out_file.write(response.read())

                # Update progress after download completes (showing final file size)
                if progress:
                    progress.update(
                        progress.current, progress.current_paper, pdf_path=pdf_path
                    )

                # Check if the file downloaded successfully (basic check: the file exists and is not empty)
                if os.path.exists(pdf_path):
                    file_size = os.path.getsize(pdf_path)
                    if (
                        file_size == 0 or file_size < 1024
                    ):  # less than1KBPossibly an error page
                        print(
                            f"[DailyArxiv] PDF File is empty or too small ({file_size} bytes),delete: {paper.arxiv_id}"
                        )
                        try:
                            os.remove(pdf_path)
                        except:
                            pass
                        return None

                print(f"[DailyArxiv] PDF Download successful: {paper.arxiv_id}")
                return pdf_path

        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(
                    f"[DailyArxiv] download PDF fail ({paper.arxiv_id}): 403 Forbidden - maybe the server IP restricted or PDF Not published yet, will try again next time we check"
                )
            else:
                print(
                    f"[DailyArxiv] download PDF fail ({paper.arxiv_id}): HTTP Error {e.code}: {e.reason}"
                )
            return None
        except Exception as e:
            print(f"[DailyArxiv] download PDF fail ({paper.arxiv_id}): {e}")
            return None

    def _generate_thumbnail(self, pdf_path: str, cat_dir: str) -> Optional[str]:
        """generatePDFthumbnail"""
        try:
            # Check if the file exists and is not empty
            if not os.path.exists(pdf_path):
                print(f"[DailyArxiv] PDF File does not exist: {pdf_path}")
                return None

            file_size = os.path.getsize(pdf_path)
            if file_size == 0 or file_size < 1024:
                print(
                    f"[DailyArxiv] PDF File is empty or too small ({file_size} bytes), skip generating thumbnails: {pdf_path}"
                )
                return None

            safe_id = os.path.splitext(os.path.basename(pdf_path))[0]
            thumbnail_filename = f"{safe_id}_thumbnail.jpg"
            thumbnail_path = os.path.join(cat_dir, thumbnail_filename)

            # If the thumbnail already exists, return directly
            if os.path.exists(thumbnail_path):
                return thumbnail_path

            # Generate thumbnails
            return generate_pdf_thumbnail(pdf_path, thumbnail_path, crop_ratio=0.5)
        except Exception as e:
            print(f"[DailyArxiv] Failed to generate thumbnail: {e}")
            return None

    def _extract_affiliations(
        self,
        pdf_path: str,
        openai_base_url: str,
        openai_api_key: str,
        model_name: str,
        prompt: str = None,
    ) -> Dict[str, Any]:
        """Extract institution information, country,homepage and github"""
        first_page_text = extract_pdf_first_page_text(pdf_path)
        if not first_page_text:
            return {
                "affiliations": [],
                "countries": [],
                "homepage": None,
                "github": None,
            }

        return extract_affiliations_with_llm(
            first_page_text,
            openai_base_url,
            openai_api_key,
            model_name,
            prompt=prompt,
            settings_file=self.settings_file,
        )

    def _save_paper(self, paper_dict: Dict, cat_dir: str):
        """Save article metadata to DB"""
        arxiv_id = paper_dict.get('arxiv_id')
        if not arxiv_id:
            return

        # Generate ID (prefix to avoid collision with main library UUIDs)
        paper_id = f"daily_{arxiv_id}"

        # Map fields
        dao_data = {
            'id': paper_id,
            'title': paper_dict.get('title'),
            'authors': paper_dict.get('authors'),
            'abstract': paper_dict.get('abstract'),
            'arxiv_published_date': paper_dict.get('published'),
            'arxiv_url': paper_dict.get('pdf_url'),
            'arxiv_id': arxiv_id,
            'subject': paper_dict.get('primary_category'),
            'upload_date': datetime.now().isoformat(),
            'file_path': paper_dict.get('local_pdf_path'),
            'thumbnail_path': paper_dict.get('thumbnail_path'),
            'is_daily': 1,
            'daily_date': paper_dict.get('fetch_date'),
            # Store extra fields in metadata column (handled by DAO)
            'categories': paper_dict.get('categories'),
            'comment': paper_dict.get('comment'),
            'journal_ref': paper_dict.get('journal_ref'),
            'affiliations': paper_dict.get('affiliations'),
            'countries': paper_dict.get('countries'),
            'homepage': paper_dict.get('homepage'),
            'github': paper_dict.get('github'),
            'summary': paper_dict.get('summary'),
            'keywords': paper_dict.get('keywords'),
            'matched_keywords': paper_dict.get('matched_keywords'),
            'fetch_category': paper_dict.get('fetch_category')
        }

        PaperDAO.save_paper(dao_data)

    def cleanup_old_papers(self, retention_days: int = 7):
        """
        Clean up expired papers

        keep recent N a date with a paper (rather than N natural day)

        Args:
            retention_days: Number of dates for which papers are retained
        """
        print(
            f"[DailyArxiv] Clean up expired papers and keep the latest ones {retention_days} date with paper..."
        )

        # Get the dates of all papers (sorted in descending order, latest first)
        available_dates = self.get_available_dates()
        print(
            f"[DailyArxiv] List of dates for which papers are currently available: {available_dates}"
        )

        if len(available_dates) <= retention_days:
            print(
                f"[DailyArxiv] Currently there are {len(available_dates)} dates with papers, less than or equal to the number reserved {retention_days}, no need to clean"
            )
            return

        # keep recent retention_days dates, delete older ones
        dates_to_keep = set(available_dates[:retention_days])
        dates_to_delete = [d for d in available_dates if d not in dates_to_keep]

        print(
            f"[DailyArxiv] will retain the following {len(dates_to_keep)} dates: {sorted(dates_to_keep, reverse=True)}"
        )
        print(
            f"[DailyArxiv] The following will be deleted {len(dates_to_delete)} expiry date: {sorted(dates_to_delete, reverse=True)}"
        )

        deleted_count = 0
        for name in dates_to_delete:
             # Delete directory
            path = self.get_date_dir(name)
            if os.path.exists(path):
                print(f"[DailyArxiv] Delete expired directory: {name}")
                try:
                    shutil.rmtree(path)
                    deleted_count += 1
                except Exception as e:
                    print(f"[DailyArxiv] Delete failed: {e}")

        # Delete from DB
        if dates_to_keep:
            oldest_date_to_keep = sorted(list(dates_to_keep))[0]
            PaperDAO.delete_old_daily_papers(oldest_date_to_keep)

        print(
            f"[DailyArxiv] Cleanup completed, deleted in total {deleted_count} Expiration date directory"
        )

    def start_scheduler(self):
        """Start scheduler"""
        if self._scheduler_running:
            return

        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True
        )
        self._scheduler_thread.start()
        print("[DailyArxiv] Scheduler started")

    def stop_scheduler(self):
        """Stop scheduler"""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        print("[DailyArxiv] Scheduler has stopped")

    def _scheduler_loop(self):
        """scheduler main loop"""
        # Execute once immediately on startup
        settings = self.get_settings()
        if settings.get("enabled", False):
            self._do_scheduled_fetch()

        while self._scheduler_running:
            settings = self.get_settings()
            
            # Check if enabled
            if not settings.get("enabled", False):
                # If disabled, check every minute
                for _ in range(60):
                    if not self._scheduler_running:
                        return
                    time.sleep(1)
                continue
            
            interval_minutes = settings.get("checkIntervalMinutes", 10)

            # wait
            for _ in range(interval_minutes * 60):
                if not self._scheduler_running:
                    return
                time.sleep(1)

            # Perform crawling
            self._do_scheduled_fetch()

    def _get_recent_weekdays(self, days: int) -> List[str]:
        """
        Get the latest N List of dates for working days (Monday to Friday)

        Args:
            days: Number of working days required

        Returns:
            List of date strings (descending order, newest first)
        """
        dates = []
        current = datetime.now().date()
        count = 0

        # Find working days starting from today and looking forward
        while count < days:
            weekday = current.weekday()  # 0=Monday, 6=Sunday
            # If it is a working day (Monday to Friday)
            if weekday < 5:
                dates.append(current.strftime("%Y-%m-%d"))
                count += 1
            # Push forward one day
            current -= timedelta(days=1)
            # Prevent infinite loops (looking up to the next 30 sky)
            if (datetime.now().date() - current).days > 30:
                break

        return dates

    def _do_scheduled_fetch(self):
        """Execution plan capture"""
        settings = self.get_settings()

        categories = settings.get("categories", [])
        retention_days = settings.get("retentionDays", 7)

        if not categories:
            print("[DailyArxiv] No partition configured")
            return

        # Test before crawling LLM API
        llm_config = {}
        if self._get_llm_config:
            llm_config = self._get_llm_config()

        llm_model = llm_config.get("llmModel", "").strip()
        llm_base_url = llm_config.get("llmBaseUrl", "").strip()
        llm_api_key = llm_config.get("llmApiKey", "").strip()

        if not llm_model or not llm_base_url or not llm_api_key:
            print(
                "[DailyArxiv] LLM API Not configured, skip this crawl. Please configure in settings LLM API Try again later."
            )
            return

        # test LLM API Is it available
        try:
            from resophy.tools.api_test_utils import test_llm_api

            print("[DailyArxiv] Testing LLM API connect...")
            success, error_msg = test_llm_api(llm_model, llm_base_url, llm_api_key)

            if not success:
                # Update status and record failure information
                self._llm_api_failed = True
                self._llm_api_error_message = error_msg
                print(
                    f"[DailyArxiv] LLM API test failed: {error_msg}, skip this crawl. Wait for the next inspection cycle."
                )
                return

            # Test successful, clear failure status
            self._llm_api_failed = False
            self._llm_api_error_message = ""
            print(
                "[DailyArxiv] LLM API The test is successful, start fetching papers..."
            )
        except Exception as e:
            # Update status and record exception information
            self._llm_api_failed = True
            self._llm_api_error_message = str(e)
            print(
                f"[DailyArxiv] LLM API Test exception: {e}, skip this crawl. Wait for the next inspection cycle."
            )
            return

        print(f"[DailyArxiv] Start scheduled crawling: {categories}")

        # 1. First check the current papers for several days
        available_dates = self.get_available_dates()
        dates_with_papers = len(available_dates)
        print(
            f"[DailyArxiv] Currently there are {dates_with_papers} date with paper: {available_dates}"
        )

        # Get the latest N working days (N = retention_days）
        recent_weekdays = self._get_recent_weekdays(retention_days)
        today = get_today_arxiv_date()
        today_date = datetime.strptime(today, "%Y-%m-%d").date()
        is_today_weekday = today_date.weekday() < 5

        # 2. Determine the date you need to crawl
        dates_to_fetch = []

        # 2.1 If today is a working day, today will always be crawled first (regardless of whether there are already papers, make sure they are complete)
        if is_today_weekday:
            dates_to_fetch.append(today)
            print(
                f"[DailyArxiv] Prioritize crawling today ({today}) thesis, ensuring completeness"
            )

        # 2.2 Process each working day in sequence from newest to oldest by date
        # For the most recent date (most recent3within working days), even if there are already papers, continue to crawl (may be incomplete)
        # For older dates, skip if paper already exists (considered complete)
        for date_str in recent_weekdays:
            if date_str == today:
                continue  # Already dealt with it today

            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_ago = (datetime.now().date() - date_obj).days

            # If the date is not in the existing date list, it needs to be fetched
            if date_str not in available_dates:
                dates_to_fetch.append(date_str)
            # If a paper already exists for that date, but it is more recent3Within working days, it may not be complete, so continue to crawl.
            elif days_ago <= 3:
                dates_to_fetch.append(date_str)
                print(
                    f"[DailyArxiv] date {date_str} Papers exist but may be incomplete ({days_ago} days ago), continue crawling to ensure completeness"
                )
            # If there is already a paper on an older date, it will be considered complete and skipped.

        # Deduplicate and sort (newest first, ensure fetching in order)
        dates_to_fetch = sorted(set(dates_to_fetch), reverse=True)

        # 2.3 If the number of dates for existing papers is less than the number of days retained, add the missing dates
        if dates_with_papers < retention_days:
            missing_dates = []
            for date_str in recent_weekdays:
                if date_str not in available_dates and date_str not in dates_to_fetch:
                    missing_dates.append(date_str)

            # Supplement missing dates until reached retention_days indivual
            needed_count = retention_days - dates_with_papers
            dates_to_fetch.extend(missing_dates[:needed_count])
            dates_to_fetch = sorted(set(dates_to_fetch), reverse=True)

        # 3. If the current paper age is greater than the setting, clean up the excess first (clean up before crawling to avoid exceeding the limit after crawling)
        if dates_with_papers > retention_days:
            print(
                f"[DailyArxiv] Currently there are {dates_with_papers} Dates with papers exceeding reserved quantity {retention_days}, clean up the excess first..."
            )
            self.cleanup_old_papers(retention_days)
            # Re-get list of dates after cleaning
            available_dates = self.get_available_dates()
            dates_with_papers = len(available_dates)
            print(
                f"[DailyArxiv] Remaining after cleaning {dates_with_papers} date with paper: {available_dates}"
            )

        # 4. Perform crawling
        if dates_to_fetch:
            print(
                f"[DailyArxiv] The following dates will be crawled in order: {dates_to_fetch}"
            )

            # Fetch each date in order (newest first)
            for date_str in dates_to_fetch:
                for category in categories:
                    try:
                        print(
                            f"[DailyArxiv] crawl {category} Partition {date_str} thesis..."
                        )
                        self.fetch_papers(category, date_str=date_str, force=False)
                    except Exception as e:
                        print(f"[DailyArxiv] crawl {category} {date_str} fail: {e}")

                    # Interval between partitions to prevent requests from being too fast
                    time.sleep(2)
        else:
            print(
                f"[DailyArxiv] All required dates are complete, no additions are needed"
            )

        # 5. After the fetching is complete, clean it again to ensure that only N days (this is a critical step)
        print(
            f"[DailyArxiv] After the crawl is complete, perform final cleanup to ensure that only {retention_days} Tian thesis..."
        )
        self.cleanup_old_papers(retention_days)

        # Verify cleanup results
        final_dates = self.get_available_dates()
        final_count = len(final_dates)
        print(
            f"[DailyArxiv] final reservation {final_count} date with paper: {final_dates}"
        )
        if final_count > retention_days:
            print(
                f"[DailyArxiv] ⚠️ Warning: There are still {final_count} dates, exceeded reserved quantity {retention_days}, there may be a cleaning logic problem"
            )
        else:
            print(
                f"[DailyArxiv] ✅ Cleanup completed, current paper days ({final_count}) Comply with settings ({retention_days})"
            )

        print("[DailyArxiv] Scheduled capture completed")


def extract_pdf_first_page_text(pdf_path: str) -> Optional[str]:
    """
    extract PDF The text content of the first page

    Args:
        pdf_path: PDF file path

    Returns:
        The first page of text, returned on failure None
    """
    try:
        # Check if the file exists and is not empty
        if not os.path.exists(pdf_path):
            return None

        file_size = os.path.getsize(pdf_path)
        if file_size == 0 or file_size < 1024:
            print(
                f"[DailyArxiv] PDF File is empty or too small ({file_size} bytes), skip extracting text: {pdf_path}"
            )
            return None

        # use PyMuPDF (fitz) Extract, which preserves whitespace better
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        if len(doc) > 0:
            page = doc[0]
            text = page.get_text()
            doc.close()
            return text if text else None
        doc.close()
        return None
    except ImportError:
        # if not PyMuPDF, downgrade to use pdfplumber
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) > 0:
                    page = pdf.pages[0]
                    text = page.extract_text()
                    return text if text else None
            return None
        except Exception as e:
            print(f"[DailyArxiv] extract PDF First page text failed (pdfplumber): {e}")
            return None
    except Exception as e:
        print(f"[DailyArxiv] extract PDF First page text failed: {e}")
        return None


def generate_pdf_thumbnail(
    pdf_path: str, output_path: str = None, crop_ratio: float = 0.5
) -> Optional[str]:
    """
    generate PDF Thumbnail of the first half of the first page

    Args:
        pdf_path: PDF file path
        output_path: Output image path (optional, defaults toPDFsame directory)
        crop_ratio: Crop ratio,0.5 Indicates the upper part

    Returns:
        Thumbnail path, returned on failure None
    """
    try:
        # Check if the file exists and is not empty
        if not os.path.exists(pdf_path):
            return None

        file_size = os.path.getsize(pdf_path)
        if file_size == 0 or file_size < 1024:
            print(
                f"[DailyArxiv] PDF File is empty or too small ({file_size} bytes), skip generating thumbnails: {pdf_path}"
            )
            return None

        import fitz  # PyMuPDF

        # If no output path is specified, usePDFSame directory
        if output_path is None:
            base_name = os.path.splitext(pdf_path)[0]
            output_path = f"{base_name}_thumbnail.jpg"

        # OpenPDF
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return None

        # Get the first page
        page = doc[0]

        # Set zoom factor (increase clarity)
        zoom = 2.0  # 2Zoom twice to generate clearer pictures
        mat = fitz.Matrix(zoom, zoom)

        # Render the first page as an image
        pix = page.get_pixmap(matrix=mat)

        # Convert toPIL Image
        try:
            from io import BytesIO

            from PIL import Image
        except ImportError:
            print(
                f"[DailyArxiv] Failed to generate thumbnail: Requires installation Pillow (pip install Pillow)"
            )
            doc.close()
            return None

        img_data = pix.tobytes("ppm")
        img = Image.open(BytesIO(img_data))

        # Get image size
        width, height = img.size

        # Cut the top half (according to crop_ratio）
        crop_height = int(height * crop_ratio)
        img_cropped = img.crop((0, 0, width, crop_height))

        # save asJPEG(Compressed to reduce file size)
        img_cropped.save(output_path, "JPEG", quality=85, optimize=True)

        doc.close()
        print(f"[DailyArxiv] Generate thumbnails: {output_path}")
        return output_path

    except ImportError:
        print(
            f"[DailyArxiv] Failed to generate thumbnail: Requires installation PyMuPDF and Pillow"
        )
        return None
    except Exception as e:
        print(f"[DailyArxiv] Failed to generate thumbnail: {e}")
        import traceback

        traceback.print_exc()
        return None


def extract_affiliations_with_llm(
    first_page_text: str,
    openai_base_url: str,
    openai_api_key: str,
    model_name: str,
    prompt: str = None,
    settings_file: str = None,
) -> Dict[str, Any]:
    """
    use LLM from PDF Extract institutional information from the text on the first page,homepage and github

    Args:
        first_page_text: PDF First page text
        openai_base_url: OpenAI API Base URL
        openai_api_key: OpenAI API key
        model_name: LLM Model name
        prompt: Custom prompt words (optional)
        settings_file: Configuration file path (optional, used to read custom institution mappings)

    Returns:
        Include affiliations, homepage, github dictionary
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        # Get available models
        try:
            models = client.models.list()
            if model_name not in [model.id for model in models.data]:
                print(f"[DailyArxiv] Model {model_name} does not exist")
                return {
                    "affiliations": [],
                    "countries": [],
                    "homepage": None,
                    "github": None,
                }
        except Exception as e:
            print(f"[DailyArxiv] Failed to get model list: {e}")
            return {
                "affiliations": [],
                "countries": [],
                "homepage": None,
                "github": None,
            }

        # Construct prompt words (use custom or default)
        system_prompt = prompt if prompt else AFFILIATION_EXTRACTION_PROMPT
        full_prompt = system_prompt + first_page_text
        messages = [{"role": "user", "content": full_prompt}]

        print(
            f"[DailyArxiv] Use model {model_name} Extract organization information,homepage and github..."
        )

        # call LLM
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model_name,
            temperature=0.1,
            max_tokens=800,  # Increase token quantity to support more information
        )

        result_content = chat_completion.choices[0].message.content.strip()

        # parse JSON Result (new format: contains affiliations, homepage, github）
        try:
            # Try to parse directly JSON
            if result_content.startswith("{"):
                result = json.loads(result_content)
            else:
                # Try to extract from text JSON
                import re

                json_match = re.search(r"\{.*\}", result_content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    # Compatible with old formats (arrays only)
                    if result_content.startswith("["):
                        affiliations = json.loads(result_content)
                        result = {
                            "affiliations": affiliations,
                            "countries": [],
                            "homepage": None,
                            "github": None,
                        }
                    else:
                        print(
                            f"[DailyArxiv] Unable to parse result: {result_content[:200]}"
                        )
                        return {
                            "affiliations": [],
                            "countries": [],
                            "homepage": None,
                            "github": None,
                        }
        except json.JSONDecodeError as e:
            print(f"[DailyArxiv] JSON Parsing failed: {e}")
            print(f"[DailyArxiv] original content: {result_content[:200]}")
            return {
                "affiliations": [],
                "countries": [],
                "homepage": None,
                "github": None,
            }

        # extract affiliations(compatible with older formats)
        affiliations = result.get("affiliations", [])
        if not isinstance(affiliations, list):
            affiliations = []

        # Remove duplicates and keep order
        seen = set()
        unique_affiliations = []
        for aff in affiliations:
            if isinstance(aff, str) and aff.strip() and aff.strip() not in seen:
                seen.add(aff.strip())
                unique_affiliations.append(aff.strip())

        # extract countries(and affiliations correspond)
        countries = result.get("countries", [])
        if not isinstance(countries, list):
            countries = []

        # make sure countries The length of the list is the same as affiliations Consistent (truncate or pad if lengths are inconsistent)
        if len(countries) > len(unique_affiliations):
            countries = countries[: len(unique_affiliations)]
        elif len(countries) < len(unique_affiliations):
            countries.extend([""] * (len(unique_affiliations) - len(countries)))

        # Remove duplicates countries(use set, but keep the order)
        unique_countries = []
        seen_countries = set()
        for country in countries:
            if isinstance(country, str) and country.strip():
                country_clean = country.strip()
                if country_clean not in seen_countries:
                    seen_countries.add(country_clean)
                    unique_countries.append(country_clean)

        # extract homepage and github
        homepage = result.get("homepage")
        github = result.get("github")

        # deal with None or empty string
        if homepage == "None" or homepage == "":
            homepage = None
        if github == "None" or github == "":
            github = None

        # Standardize URL(If there is no agreement, add https://）
        if homepage and not homepage.startswith(("http://", "https://")):
            homepage = f"https://{homepage}"
        if github and not github.startswith(("http://", "https://")):
            github = f"https://{github}"

        print(
            f"[DailyArxiv] Extract to {len(unique_affiliations)} institutions: {unique_affiliations}"
        )
        if unique_countries:
            print(
                f"[DailyArxiv] Extract to {len(unique_countries)} countries: {unique_countries}"
            )
        if homepage:
            print(f"[DailyArxiv] Homepage: {homepage}")
        if github:
            print(f"[DailyArxiv] GitHub: {github}")

        # Standardization body name (unification of various variants into a standard abbreviation)
        try:
            import os
            import sys

            # Add to tools Directory to Python path
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            tools_dir = os.path.join(parent_dir, "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            from resophy.tools.institution_normalizer import (
                InstitutionNormalizer,
            )  # type: ignore

            # Create a normalizer instance (containing system mapping + User-defined mapping)
            # settings_file The parameter passed in is the configuration file path (if any)
            normalizer = InstitutionNormalizer(custom_mapping_file=settings_file)
            normalized_affiliations = normalizer.normalize_list(unique_affiliations)

            # If the standardized institution list is different from the original list, print the log
            if normalized_affiliations != unique_affiliations:
                print(f"[DailyArxiv] before standardization: {unique_affiliations}")
                print(f"[DailyArxiv] After standardization: {normalized_affiliations}")

            unique_affiliations = normalized_affiliations
        except Exception as e:
            print(
                f"[DailyArxiv] Organization name normalization failed (original name used): {e}"
            )
            import traceback

            traceback.print_exc()

        return {
            "affiliations": unique_affiliations,
            "countries": unique_countries,
            "homepage": homepage,
            "github": github,
        }

    except Exception as e:
        print(f"[DailyArxiv] Failed to extract organization information: {e}")
        import traceback

        traceback.print_exc()
        return {"affiliations": [], "homepage": None, "github": None}


def extract_summary_and_keywords_with_llm(
    abstract: str,
    openai_base_url: str,
    openai_api_key: str,
    model_name: str,
    prompt: str = None,
) -> Dict[str, Any]:
    """
    use LLM Extract summary and keywords from paper abstract

    Args:
        abstract: Abstract of thesis (English)
        openai_base_url: OpenAI API Base URL
        openai_api_key: OpenAI API key
        model_name: LLM Model name
        prompt: Custom prompt words (optional)

    Returns:
        Include summary and keywords dictionary
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        # Get available models
        try:
            models = client.models.list()
            if model_name not in [model.id for model in models.data]:
                print(f"[DailyArxiv] Model {model_name} does not exist")
                return {"summary": None, "keywords": []}
        except Exception as e:
            print(f"[DailyArxiv] Failed to get model list: {e}")
            return {"summary": None, "keywords": []}

        # Construct prompt words (use custom or default)
        system_prompt = prompt if prompt else SUMMARY_EXTRACTION_PROMPT
        # if prompt Contains {keyword_list} Placeholder, needs to be replaced before use (but here it should have been replaced before calling)
        full_prompt = system_prompt + abstract
        messages = [{"role": "user", "content": full_prompt}]

        print(f"[DailyArxiv] Use model {model_name} Extract abstracts and keywords...")

        # call LLM
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model_name,
            temperature=0.3,
            max_tokens=800,
        )

        result_content = chat_completion.choices[0].message.content.strip()

        # parse JSON result
        import re

        # Try to parse directly
        if result_content.startswith("{"):
            result = json.loads(result_content)
        else:
            # Try to extract from text JSON
            json_match = re.search(r"\{.*\}", result_content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                print(
                    f"[DailyArxiv] Unable to parse abstract and keywords: {result_content[:200]}"
                )
                return {"summary": None, "keywords": []}

        summary = result.get("summary", "")
        keywords = result.get("keywords", [])

        # make sure keywords is a list
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]

        print(f"[DailyArxiv] Extract keywords: {keywords}")
        return {"summary": summary, "keywords": keywords}

    except json.JSONDecodeError as e:
        print(f"[DailyArxiv] JSON Parsing failed: {e}")
        return {"summary": None, "keywords": []}
    except Exception as e:
        print(f"[DailyArxiv] Failed to extract abstracts and keywords: {e}")
        import traceback

        traceback.print_exc()
        return {"summary": None, "keywords": []}


# Global manager instance
_manager_instance: Optional[DailyArxivManager] = None


def get_manager(base_dir: str, settings_file: str) -> DailyArxivManager:
    """Get global manager instance"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = DailyArxivManager(base_dir, settings_file)
    return _manager_instance


# Compatible with old interfaces
class DailyArxivFetcher:
    """Old interface compatibility layer"""

    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3.0,
            num_retries=3,
        )

    def fetch_latest_papers(
        self,
        category: str,
        max_results: int = 3,
        days_back: int = 7,
    ) -> List[ArxivPaper]:
        try:
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            papers = []
            for result in self.client.results(search):
                paper = ArxivPaper.from_arxiv_result(result, fetch_category=category)
                papers.append(paper)

            print(f"[DailyArxiv] from {category} Got {len(papers)} papers")
            return papers

        except Exception as e:
            print(f"[DailyArxiv] get {category} Thesis failed: {e}")
            return []


def get_fetcher(temp_dir: str) -> DailyArxivFetcher:
    """get old style fetcher Example"""
    return DailyArxivFetcher(temp_dir)
