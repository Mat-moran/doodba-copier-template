from pathlib import Path

import pytest
from copier import copy
from plumbum import ProcessExecutionError, local
from plumbum.cmd import docker_compose, invoke
from plumbum.machines.local import LocalCommand

from .conftest import build_file_tree, socket_is_open


def _install_status(module, dbname="devel"):
    return docker_compose(
        "run",
        "--rm",
        "-e",
        "LOG_LEVEL=WARNING",
        "-e",
        f"PGDATABASE={dbname}",
        "odoo",
        "psql",
        "-tc",
        f"select state from ir_module_module where name='{module}'",
    ).strip()


def test_resetdb(
    cloned_template: Path,
    docker: LocalCommand,
    supported_odoo_version: float,
    tmp_path: Path,
):
    """Test the dropdb task.

    On this test flow, other downsream tasks are also tested:

    - img-build
    - git-aggregate
    - stop --purge
    """
    try:
        with local.cwd(tmp_path):
            copy(
                src_path=str(cloned_template),
                vcs_ref="HEAD",
                force=True,
                data={"odoo_version": supported_odoo_version},
            )
            # Imagine the user is in the src subfolder for these tasks
            with local.cwd(tmp_path / "odoo" / "custom" / "src"):
                invoke("img-build")
                invoke("git-aggregate")
            # No ir_module_module table exists yet
            with pytest.raises(ProcessExecutionError):
                _install_status("base")
            # Imagine the user is in the odoo subrepo for these tasks
            with local.cwd(tmp_path / "odoo" / "custom" / "src" / "odoo"):
                # This should install just "base"
                stdout = invoke("resetdb")
            assert "Creating database cache" in stdout
            assert "from template devel" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "uninstalled"
            assert _install_status("sale") == "uninstalled"
            # Install "purchase"
            stdout = invoke("resetdb", "-m", "purchase")
            assert "Creating database cache" in stdout
            assert "from template devel" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "installed"
            assert _install_status("sale") == "uninstalled"
            # Install "sale" in a separate database
            stdout = invoke("resetdb", "-m", "sale", "-d", "sale_only")
            assert "Creating database cache" in stdout
            assert "from template sale_only" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "installed"
            assert _install_status("sale") == "uninstalled"
            assert _install_status("base", "sale_only") == "installed"
            assert _install_status("purchase", "sale_only") == "uninstalled"
            assert _install_status("sale", "sale_only") == "installed"
            # Install "sale" in main database
            stdout = invoke("resetdb", "-m", "sale")
            assert "Creating database devel from template cache" in stdout
            assert "Found matching database template" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "uninstalled"
            assert _install_status("sale") == "installed"
    finally:
        # Imagine the user is in the odoo subrepo for this command
        with local.cwd(tmp_path / "odoo" / "custom" / "src" / "odoo"):
            invoke("stop", "--purge")


@pytest.mark.sequential
def test_start(
    cloned_template: Path,
    docker: LocalCommand,
    supported_odoo_version: float,
    tmp_path: Path,
):
    """Test the start task.

    On this test flow, other downsream tasks are also tested:

    - img-build
    - git-aggregate
    - stop --purge
    """
    try:
        with local.cwd(tmp_path):
            copy(
                src_path=str(cloned_template),
                vcs_ref="HEAD",
                force=True,
                data={"odoo_version": supported_odoo_version},
            )
            # Imagine the user is in the src subfolder for these tasks
            with local.cwd(tmp_path / "odoo" / "custom" / "src"):
                invoke("img-build")
                invoke("git-aggregate")
            # Test normal call
            stdout = invoke("start")
            print(stdout)
            assert "Reinitialized existing Git repository" in stdout
            assert "pre-commit installed" in stdout
            # Test "--debugpy and wait time call
            invoke("stop")
            stdout = invoke("start", "--debugpy")
            assert socket_is_open("127.0.0.1", int(supported_odoo_version) * 1000 + 899)
            # Check if auto-reload is disabled
            container_logs = invoke("logs")
            assert "dev=reload" not in container_logs
    finally:
        # Imagine the user is in the odoo subrepo for this command
        with local.cwd(tmp_path / "odoo" / "custom" / "src" / "odoo"):
            invoke("stop", "--purge")


@pytest.mark.sequential
def test_install(
    cloned_template: Path,
    docker: LocalCommand,
    supported_odoo_version: float,
    tmp_path: Path,
):
    """Test the install task.

    On this test flow, other downsream tasks are also tested:

    - img-build
    - git-aggregate
    - stop --purge
    """
    try:
        with local.cwd(tmp_path):
            copy(
                src_path=str(cloned_template),
                vcs_ref="HEAD",
                force=True,
                data={"odoo_version": supported_odoo_version},
            )
            # Imagine the user is in the src subfolder for these tasks
            # and the DB is clean
            with local.cwd(tmp_path / "odoo" / "custom" / "src"):
                invoke("img-build")
                invoke("git-aggregate")
                invoke("resetdb")
            # No ir_module_module table exists yet
            with pytest.raises(ProcessExecutionError):
                _install_status("base")
            # This should install just "base"
            stdout = invoke("install", "-m", "base")
            assert "Executing odoo --stop-after-init --init base" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "uninstalled"
            assert _install_status("sale") == "uninstalled"
            # Install "purchase"
            stdout = invoke("install", "-m", "purchase")
            assert "Executing odoo --stop-after-init --init purchase" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "installed"
            assert _install_status("sale") == "uninstalled"
            # Change to "sale" subfolder and install
            with local.cwd(
                tmp_path / "odoo" / "custom" / "src" / "odoo" / "addons" / "sale"
            ):
                # Install "sale"
                stdout = invoke("install")
                assert "Executing odoo --stop-after-init --init sale" in stdout
                assert _install_status("base") == "installed"
                assert _install_status("purchase") == "installed"
                assert _install_status("sale") == "installed"
            # Install all core addons
            stdout = invoke("install", "--core")
            assert "Executing addons init --core" in stdout
            assert _install_status("base") == "installed"
            assert _install_status("purchase") == "installed"
            assert _install_status("sale") == "installed"
            assert _install_status("account") == "installed"
            # Install private addon
            with local.cwd(tmp_path / "odoo" / "custom" / "src" / "private"):
                # Generate generic addon path
                is_py3 = supported_odoo_version >= 11
                manifest = "__manifest__" if is_py3 else "__openerp__"
                build_file_tree(
                    {
                        f"test_module_static/{manifest}.py": f"""\
                            {"{"}
                            'name':'test module','license':'AGPL-3',
                            'version':'{supported_odoo_version}.1.0.0',
                            'installable': True,
                            'auto_install': False
                            {"}"}
                        """,
                        "test_module_static/static/index.html": """\
                            <html>
                            </html>
                        """,
                    }
                )
            stdout = invoke("install", "--private")
            assert (
                "Executing odoo --stop-after-init --init test_module_static" in stdout
            )
            assert _install_status("test_module_static") == "installed"

    finally:
        # Imagine the user is in the odoo subrepo for this command
        with local.cwd(tmp_path / "odoo" / "custom" / "src" / "odoo"):
            invoke("stop", "--purge")


@pytest.mark.sequential
def test_test(
    cloned_template: Path,
    docker: LocalCommand,
    supported_odoo_version: float,
    tmp_path: Path,
):
    """Test the test task.

    On this test flow, other downsream tasks are also tested:

    - img-build
    - git-aggregate
    - stop --purge
    """
    try:
        with local.cwd(tmp_path):
            copy(
                src_path=str(cloned_template),
                vcs_ref="HEAD",
                force=True,
                data={"odoo_version": supported_odoo_version},
            )
            # Imagine the user is in the src subfolder for these tasks
            with local.cwd(tmp_path / "odoo" / "custom" / "src"):
                invoke("img-build")
                invoke("git-aggregate")
            # This should test just "purchase"
            stdout = invoke("test", "-m", "purchase")
            assert "Executing odoo --test-enable -i purchase" in stdout
            # Change to "sale" subfolder and test
            with local.cwd(
                tmp_path / "odoo" / "custom" / "src" / "odoo" / "addons" / "sale"
            ):
                # Test "sale"
                stdout = invoke("test")
                assert "Executing odoo --test-enable -i sale" in stdout
            # Test "--debugpy and wait time call
            invoke("stop")
            stdout = invoke("test", "-m", "sale", "--debugpy")
            assert socket_is_open("127.0.0.1", int(supported_odoo_version) * 1000 + 899)
    finally:
        # Imagine the user is in the odoo subrepo for this command
        with local.cwd(tmp_path / "odoo" / "custom" / "src" / "odoo"):
            invoke("stop", "--purge")
