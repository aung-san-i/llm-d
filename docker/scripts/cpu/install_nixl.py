# install_prerequisites.py
import os
import subprocess
import sys
import argparse
import glob

# --- Configuration ---
WHEELS_CACHE_HOME = os.environ.get("WHEELS_CACHE_HOME", "/workspace/wheels_cache")
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
UCX_DIR = os.path.join('/tmp', 'ucx_source')
NIXL_DIR = os.path.join('/tmp', 'nixl_source')
UCX_INSTALL_DIR = os.path.join('/tmp', 'ucx_install')
UCX_REPO_URL = 'https://github.com/openucx/ucx.git'
NIXL_REPO_URL = 'https://github.com/ai-dynamo/nixl.git'


# --- Helper Functions ---
def run_command(command, cwd='.', env=None):
    """Helper function to run a shell command and check for errors."""
    print(f"--> Running command: {' '.join(command)} in '{cwd}'", flush=True)
    subprocess.check_call(command, cwd=cwd, env=env)


def is_pip_package_installed(package_name):
    """Checks if a package is installed via pip without raising an exception."""
    result = subprocess.run([sys.executable, '-m', 'pip', 'show', package_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return result.returncode == 0


def find_nixl_wheel_in_cache(cache_dir):
    """Finds a nixl wheel file in the specified cache directory."""
    # The repaired wheel will have a 'manylinux' tag, but this glob still works.
    search_pattern = os.path.join(cache_dir, "nixl*.whl")
    wheels = glob.glob(search_pattern)
    if wheels:
        # Sort to get the most recent/highest version if multiple exist
        wheels.sort()
        return wheels[-1]
    return None


def detect_distro():
    """Detect if running on a Red Hat derivative or Debian derivative."""
    if os.path.exists('/etc/redhat-release'):
        return 'rhel'
    if os.path.exists('/etc/os-release'):
        with open('/etc/os-release') as f:
            content = f.read().lower()
            for keyword in ('rhel', 'redhat', 'centos', 'fedora', 'rocky', 'alma', 'ubi'):
                if keyword in content:
                    return 'rhel'
    return 'debian'


def get_package_manager():
    """Return the appropriate package manager command for the distro."""
    for cmd in ['dnf', 'yum']:
        if subprocess.run(['which', cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return cmd
    return None


def install_system_dependencies():
    """Installs required system packages using dnf/yum for RHEL or apt-get for Debian."""
    if os.geteuid() != 0:
        print("\n---", flush=True)
        print("WARNING: Not running as root. Skipping system dependency installation.", flush=True)
        print("Please ensure the required build packages are installed on your system.", flush=True)
        print("---\n", flush=True)
        return

    distro = detect_distro()
    print(f"--- Running as root. Detected distro family: {distro}. Installing system dependencies... ---", flush=True)

    if distro == 'rhel':
        pkg_mgr = get_package_manager()
        if not pkg_mgr:
            raise RuntimeError("Neither dnf nor yum found on this Red Hat system.")

        # Enable CRB/PowerTools for build dependencies if available
        if pkg_mgr == 'dnf':
            for repo_name in ['crb', 'powertools', 'codeready-builder']:
                result = subprocess.run([pkg_mgr, 'config-manager', '--set-enabled', repo_name],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode == 0:
                    print(f"--> Enabled repository: {repo_name}", flush=True)
                    break

        rhel_packages = [
            "patchelf",
            "gcc",
            "gcc-c++",
            "make",
            "git",
            "cmake",
            "ninja-build",
            "autoconf",
            "automake",
            "meson",
            "libtool",
            "rdma-core-devel",
            "numactl-devel",
        ]
        run_command([pkg_mgr, 'install', '-y'] + rhel_packages)

        # Install EPEL if patchelf or other packages were not found
        result = subprocess.run(['which', 'patchelf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            print("--> patchelf not found, attempting to install EPEL and retry...", flush=True)
            subprocess.run([pkg_mgr, 'install', '-y', 'epel-release'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run_command([pkg_mgr, 'install', '-y', 'patchelf'])

    else:
        # Debian/Ubuntu fallback
        apt_packages = [
            "patchelf",
            "build-essential",
            "git",
            "cmake",
            "ninja-build",
            "autotools-dev",
            "automake",
            "meson",
            "libtool",
            "libtool-bin"
        ]
        run_command(['apt-get', 'update'])
        run_command(['apt-get', 'install', '-y'] + apt_packages)

    print("--- System dependencies installed successfully. ---\n", flush=True)


def build_and_install_prerequisites(args):
    """Builds UCX and NIXL from source, creating a self-contained wheel."""

    # ... (initial checks and setup are unchanged) ...
    if not args.force_reinstall and is_pip_package_installed('nixl'):
        print("--> NIXL is already installed. Nothing to do.", flush=True)
        return

    cached_wheel = find_nixl_wheel_in_cache(WHEELS_CACHE_HOME)
    if not args.force_reinstall and cached_wheel:
        print(f"\n--> Found self-contained wheel: {os.path.basename(cached_wheel)}.", flush=True)
        print("--> Installing from cache, skipping all source builds.", flush=True)
        install_command = [sys.executable, '-m', 'pip', 'install', cached_wheel]
        run_command(install_command)
        print("\n--- Installation from cache complete. ---", flush=True)
        return

    print("\n--> No installed package or cached wheel found. Starting full build process...", flush=True)
    print("\n--> Installing auditwheel...", flush=True)
    run_command([sys.executable, '-m', 'pip', 'install', 'auditwheel'])
    install_system_dependencies()
    ucx_install_path = os.path.abspath(UCX_INSTALL_DIR)
    print(f"--> Using wheel cache directory: {WHEELS_CACHE_HOME}", flush=True)
    os.makedirs(WHEELS_CACHE_HOME, exist_ok=True)

    # -- Step 1: Build UCX from source --
    # ... (UCX build process is unchanged) ...
    print("\n[1/3] Configuring and building UCX from source...", flush=True)
    if not os.path.exists(UCX_DIR):
        run_command(['git', 'clone', UCX_REPO_URL, UCX_DIR])
    ucx_source_path = os.path.abspath(UCX_DIR)
    run_command(['git', 'checkout', 'v1.19.x'], cwd=ucx_source_path)
    run_command(['./autogen.sh'], cwd=ucx_source_path)
    configure_command = [
        './configure',
        f'--prefix={ucx_install_path}',
        '--enable-shared',
        '--disable-static',
        '--disable-doxygen-doc',
        '--enable-optimizations',
        '--enable-cma',
        '--enable-devel-headers',
        '--with-verbs',
        '--enable-mt',
    ]
    run_command(configure_command, cwd=ucx_source_path)
    run_command(['make', '-j', str(os.cpu_count() or 1)], cwd=ucx_source_path)
    run_command(['make', 'install'], cwd=ucx_source_path)
    print("--- UCX build and install complete ---", flush=True)

    # -- Step 2: Build NIXL wheel from source --
    print("\n[2/3] Building NIXL wheel from source...", flush=True)
    if not os.path.exists(NIXL_DIR):
        run_command(['git', 'clone', NIXL_REPO_URL, NIXL_DIR])

    run_command(['git', 'fetch', '--all'], cwd=NIXL_DIR)
    run_command(['git', 'checkout', 'tags/0.6.1', '-b', 'release-0.6.1'], cwd=NIXL_DIR)

    build_env = os.environ.copy()
    build_env['PKG_CONFIG_PATH'] = os.path.join(ucx_install_path, 'lib', 'pkgconfig')
    ucx_lib_path = os.path.join(ucx_install_path, 'lib')
    ucx_plugin_path = os.path.join(ucx_lib_path, 'ucx')
    existing_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
    build_env['LD_LIBRARY_PATH'] = f"{ucx_lib_path}:{ucx_plugin_path}:{existing_ld_path}".strip(':')
    print(f"--> Using LD_LIBRARY_PATH: {build_env['LD_LIBRARY_PATH']}", flush=True)

    temp_wheel_dir = os.path.join(ROOT_DIR, 'temp_wheelhouse')
    run_command([sys.executable, '-m', 'pip', 'wheel', '.', '--no-deps', f'--wheel-dir={temp_wheel_dir}'],
                cwd=os.path.abspath(NIXL_DIR),
                env=build_env)

    # -- Step 3: Repair the wheel, excluding the already-bundled plugin --
    print("\n[3/3] Repairing NIXL wheel to include UCX libraries...", flush=True)
    unrepaired_wheel = find_nixl_wheel_in_cache(temp_wheel_dir)
    if not unrepaired_wheel:
        raise RuntimeError("Failed to find the NIXL wheel after building it.")

    # --- 👇 THE CORRECTED COMMAND 👇 ---
    # We tell auditwheel to ignore the plugin that mesonpy already handled.
    auditwheel_command = [
        'auditwheel',
        'repair',
        '--exclude',
        'libplugin_UCX.so',  # <-- Exclude the problematic library
        unrepaired_wheel,
        f'--wheel-dir={WHEELS_CACHE_HOME}'
    ]
    run_command(auditwheel_command, env=build_env)
    # --- 👆 END CORRECTION 👆 ---

    # --- CLEANUP ---
    # No more temporary files to remove, just the temp wheelhouse
    run_command(['rm', '-rf', temp_wheel_dir])
    # --- END CLEANUP ---

    newly_built_wheel = find_nixl_wheel_in_cache(WHEELS_CACHE_HOME)
    if not newly_built_wheel:
        raise RuntimeError("Failed to find the repaired NIXL wheel.")

    print(f"--> Successfully built self-contained wheel: {os.path.basename(newly_built_wheel)}. Now installing...",
          flush=True)
    install_command = [sys.executable, '-m', 'pip', 'install', newly_built_wheel]
    if args.force_reinstall:
        install_command.insert(-1, '--force-reinstall')

    run_command(install_command)
    print("--- NIXL installation complete ---", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and install UCX and NIXL dependencies.")
    parser.add_argument('--force-reinstall',
                        action='store_true',
                        help='Force rebuild and reinstall of UCX and NIXL even if they are already installed.')
    args = parser.parse_args()
    build_and_install_prerequisites(args)
