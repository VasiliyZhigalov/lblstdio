"""Command-line client for the lblstdio REST API (Python 3.10+)."""

import argparse
import getpass
import hashlib
from http.client import HTTPException
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url):
        url = urlsplit(base_url)
        if (
            not url.hostname
            or url.username is not None
            or url.query
            or url.fragment
            or (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1", "localhost"})
            )
        ):
            raise ValueError("Use an HTTPS server URL, or HTTP on loopback for local testing.")
        self.base_url = base_url.rstrip("/")
        state_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
        server_key = hashlib.sha256(self.base_url.encode()).hexdigest()
        self.cookie_path = state_dir / "lblstdio-cli" / f"{server_key}.cookies"
        self.cookies = http.cookiejar.MozillaCookieJar(str(self.cookie_path))
        try:
            self.cookies.load(ignore_discard=True)
        except FileNotFoundError:
            pass
        self.opener = build_opener(NoRedirects(), HTTPCookieProcessor(self.cookies))

    def open(self, method, path, *, payload=None, headers=None):
        headers = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + "/api/v1" + path, data, headers, method=method)
        try:
            return self.opener.open(request, timeout=30)
        except HTTPError as error:
            with error:
                try:
                    body = json.load(error)
                except (ValueError, UnicodeError):
                    body = {}
                detail = body.get("detail", error.reason) if isinstance(body, dict) else body
                if path == "/auth/login" and error.code == 422:
                    detail = "Invalid login input."
            raise ApiError(error.code, detail) from error

    def call(self, method, path, *, payload=None, headers=None):
        with self.open(method, path, payload=payload, headers=headers) as response:
            result = None if response.status == 204 else json.load(response)
            return result, response.headers.get("X-Annotation-Revision")

    def save_session(self):
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(dir=self.cookie_path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
        try:
            self.cookies.save(str(temp_path), ignore_discard=True)
            temp_path.replace(self.cookie_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def download(self, path, destination):
        with self.open("GET", path) as response:
            content_type = response.headers.get_content_type()
            with destination.open("xb") as output:
                try:
                    shutil.copyfileobj(response, output)
                    length = response.headers.get("Content-Length")
                    if length is not None and output.tell() != int(length):
                        raise OSError("Incomplete image download.")
                    output.flush()
                except BaseException:
                    output.close()
                    destination.unlink()
                    raise
        return {"path": str(destination.resolve()), "content_type": content_type}


def identifier(value):
    try:
        return str(UUID(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Invalid UUID: {value}") from error


def nonnegative(value):
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("Expected a nonnegative integer.")
    return result


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--url", default=os.environ.get("LBLSTDIO_URL"), help="Server base URL")
    groups = root.add_subparsers(dest="group", required=True)

    def commands(group):
        return groups.add_parser(group).add_subparsers(dest="command", required=True)

    auth = commands("auth")
    login = auth.add_parser("login")
    login.add_argument("username", nargs="?")
    password_source = login.add_mutually_exclusive_group()
    password_source.add_argument("--password-stdin", action="store_true")
    password_source.add_argument("--credentials-file", type=Path, help="JSON file with url, username and password")
    auth.add_parser("whoami")
    auth.add_parser("logout")

    project = commands("project")
    project.add_parser("list")
    project.add_parser("classes").add_argument("project", type=identifier)
    create = project.add_parser("create")
    create.add_argument("name")
    create.add_argument("--description")
    create.add_argument("--task-type", choices=("detection", "classification"), default="detection")

    image = commands("image")
    images = image.add_parser("list")
    images.add_argument("project", type=identifier)
    images.add_argument("--status")
    images.add_argument("--limit", type=nonnegative, default=48)
    images.add_argument("--offset", type=nonnegative, default=0)
    image.add_parser("show").add_argument("image", type=identifier)
    download = image.add_parser("download")
    download.add_argument("image", type=identifier)
    download.add_argument("--out", type=Path, required=True)

    review = commands("review")
    queue = review.add_parser("list")
    queue.add_argument("project", type=identifier)
    queue.add_argument("--session", type=identifier)
    queue.add_argument("--state", choices=("all", "available", "mine", "DONE", "ISSUE"), default="all")
    queue.add_argument("--offset", type=nonnegative, default=0)
    enqueue = review.add_parser("enqueue")
    enqueue.add_argument("project", type=identifier)
    enqueue.add_argument("images", type=identifier, nargs="+")
    claim = review.add_parser("claim")
    claim.add_argument("project", type=identifier)
    claim.add_argument("--image", type=identifier)
    claim.add_argument("--session", type=identifier)

    for name in (
        "verify", "delete-box", "save-boxes", "set-label", "confirm-label",
        "finish", "release", "heartbeat", "background",
    ):
        action = review.add_parser(name)
        if name in {"finish", "release", "heartbeat", "background"}:
            action.add_argument("project", type=identifier)
        action.add_argument("image", type=identifier)
        action.add_argument("--session", type=identifier, required=True)
        if name != "heartbeat":
            action.add_argument("--revision", type=nonnegative, required=True)
        if name in {"verify", "delete-box"}:
            action.add_argument("annotation", type=identifier)
        if name == "save-boxes":
            action.add_argument("file", type=Path, help="JSON array replacing every box on the frame")
        if name == "set-label":
            action.add_argument("class_id", type=identifier)

    dataset = commands("dataset")
    build = dataset.add_parser("build")
    build.add_argument("project", type=identifier)
    build.add_argument("--name")
    build.add_argument("--train-ratio", type=float, default=0.8)
    dataset_status = dataset.add_parser("status")
    dataset_status.add_argument("project", type=identifier)
    dataset_status.add_argument("job", type=identifier)
    dataset.add_parser("list").add_argument("project", type=identifier)

    train = commands("train")
    start = train.add_parser("start")
    start.add_argument("project", type=identifier)
    start.add_argument("dataset", type=identifier)
    start.add_argument("--schedule", choices=("now", "night"), default="night")
    start.add_argument("--epochs", type=int, default=100)
    start.add_argument("--batch-size", type=int, default=16)
    start.add_argument("--imgsz", type=int, default=640)
    start.add_argument("--device", default="auto")
    weights = start.add_mutually_exclusive_group()
    weights.add_argument("--base-weights")
    weights.add_argument("--base-model", type=identifier)
    train.add_parser("status").add_argument("job", type=identifier)

    stream = commands("stream")
    stream.add_parser("list").add_argument("project", type=identifier)
    for name in ("start", "stop", "status"):
        stream.add_parser(name).add_argument("stream", type=identifier)

    task = commands("task")
    task_list = task.add_parser("list")
    task_list.add_argument("--limit", type=nonnegative, default=20)
    task_list.add_argument("--offset", type=nonnegative, default=0)
    return root


def review_command(client, args):
    command = args.command
    session = getattr(args, "session", None) or str(uuid4())
    headers = {"X-Annotation-Session": session}
    if command in {"list", "enqueue", "claim", "finish", "release", "heartbeat", "background"}:
        queue = f"/projects/{args.project}/annotation-queue"
        if command == "list":
            if args.state == "mine" and args.session is None:
                raise ValueError("Use --session with --state mine.")
            query = urlencode({"state": args.state, "offset": args.offset})
            result, _ = client.call("GET", f"{queue}?{query}", headers=headers)
            return result
        if command == "enqueue":
            result, _ = client.call("POST", f"{queue}/enqueue", payload={"ids": args.images})
            return result
        if command == "claim":
            result, _ = client.call("POST", f"{queue}/claim", payload={"image_id": args.image}, headers=headers)
            return {**result, "session": session}
        payload = {"action": command, "revision": getattr(args, "revision", 0)}
        result, _ = client.call("POST", f"{queue}/{args.image}/action", payload=payload, headers=headers)
        return result

    headers["X-Annotation-Revision"] = str(args.revision)
    image = f"/images/{args.image}"
    if command == "verify":
        method, path, payload = "POST", f"{image}/annotations/{args.annotation}/verify", None
    elif command == "delete-box":
        method, path, payload = "DELETE", f"{image}/annotations/{args.annotation}", None
    elif command == "save-boxes":
        boxes = json.loads(args.file.read_text(encoding="utf-8-sig"))
        if not isinstance(boxes, list) or not boxes or not all(isinstance(box, dict) for box in boxes):
            raise ValueError("Provide a nonempty JSON array of boxes. Use 'review background' for empty frames.")
        method, path, payload = "PUT", f"{image}/annotations", {"boxes": boxes}
    elif command == "set-label":
        method, path, payload = "PUT", f"{image}/label", {"class_id": args.class_id}
    else:
        method, path, payload = "POST", f"{image}/label/confirm", None
    result, revision = client.call(method, path, payload=payload, headers=headers)
    return {"revision": int(revision) if revision is not None else None, "result": result}


def login_details(args):
    if args.credentials_file is not None:
        if args.username is not None:
            raise ValueError("Use either a username or --credentials-file.")
        credentials = json.loads(args.credentials_file.read_text(encoding="utf-8-sig"))
        if not isinstance(credentials, dict) or not all(
            isinstance(credentials.get(key), str) and credentials[key]
            for key in ("url", "username", "password")
        ):
            raise ValueError("Credentials file must contain nonempty url, username and password strings.")
        if args.url and args.url.rstrip("/") != credentials["url"].rstrip("/"):
            raise ValueError("The credentials file URL differs from the configured server URL.")
        return credentials["url"], {"username": credentials["username"], "password": credentials["password"]}

    if not args.url:
        raise ValueError("Set LBLSTDIO_URL or pass --url.")
    if not args.username:
        raise ValueError("Provide a username or --credentials-file.")
    password = (
        sys.stdin.readline().rstrip("\r\n") if args.password_stdin
        else getpass.getpass("lblstdio password: ")
    )
    if not password:
        raise ValueError("Password is empty.")
    return args.url, {"username": args.username, "password": password}


def run(client, args):
    project = f"/projects/{getattr(args, 'project', '')}"
    image = f"/images/{getattr(args, 'image', '')}"
    match args.group, args.command:
        case "auth", "logout":
            client.call("POST", "/auth/logout")
            client.cookie_path.unlink(missing_ok=True)
            return {"logged_out": True}
        case "auth", "whoami":
            return client.call("GET", "/auth/me")[0]
        case "project", "list":
            return client.call("GET", "/projects")[0]
        case "project", "classes":
            return client.call("GET", f"{project}/classes")[0]
        case "project", "create":
            payload = {
                "name": args.name,
                "description": args.description,
                "task_type": args.task_type.upper(),
            }
            return client.call("POST", "/projects", payload=payload)[0]
        case "image", "list":
            filters = {"limit": args.limit, "offset": args.offset}
            if args.status:
                filters["status"] = args.status
            return client.call("GET", f"{project}/images?{urlencode(filters)}")[0]
        case "image", "show":
            return client.call("GET", image)[0]
        case "image", "download":
            return client.download(f"{image}/file", args.out)
        case "review", _:
            return review_command(client, args)
        case "dataset", "build":
            payload = {"name": args.name, "train": args.train_ratio, "valid": 1 - args.train_ratio}
            return client.call("POST", f"{project}/dataset-versions/jobs", payload=payload)[0]
        case "dataset", "status":
            return client.call("GET", f"{project}/data/imports/{args.job}")[0]
        case "dataset", "list":
            return client.call("GET", f"{project}/dataset-versions")[0]
        case "train", "start":
            payload = {
                "dataset_version_id": args.dataset, "schedule_mode": args.schedule,
                "epochs": args.epochs, "batch_size": args.batch_size, "imgsz": args.imgsz,
                "device": args.device, "base_weights": args.base_weights,
                "base_model_version_id": args.base_model,
            }
            return client.call("POST", f"{project}/train", payload=payload)[0]
        case "train", "status":
            return client.call("GET", f"/training-jobs/{args.job}")[0]
        case "stream", "list":
            return client.call("GET", f"{project}/streams")[0]
        case "stream", command:
            method = "GET" if command == "status" else "POST"
            return client.call(method, f"/streams/{args.stream}/{command}")[0]
        case "task", "list":
            return client.call("GET", f"/tasks?limit={args.limit}&offset={args.offset}")[0]


def main():
    cli = parser()
    args = cli.parse_args()
    try:
        if (args.group, args.command) == ("auth", "login"):
            url, credentials = login_details(args)
            client = Client(url)
            result, _ = client.call("POST", "/auth/login", payload=credentials)
            client.save_session()
        else:
            if not args.url:
                cli.error("Set LBLSTDIO_URL or pass --url.")
            result = run(Client(args.url), args)
    except ApiError as error:
        print(json.dumps({"status": error.status, "error": error.detail}, default=str), file=sys.stderr)
        return 1
    except (OSError, ValueError, HTTPException) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
