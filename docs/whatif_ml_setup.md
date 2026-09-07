# Running the What-If ML methodology on your machine

The Delta Model needs nothing beyond the backend and prices every scenario in
this product. **You do not need any of this to use What-If Analysis.** It is
only for the second methodology, which fits an XGBoost model to historical
Corporate IFRS 9 outcomes and offers a second opinion on the same shocked book.

## Why there is anything to install at all

XGBoost is a Python wrapper around a compiled library, and that library needs a
system OpenMP runtime. `uv sync` installs the Python package; it does not
install the system library, and on two of the three platforms it is missing by
default.

When it is missing, `import xgboost` raises something like

```
XGBoostError: ... Library not loaded: @rpath/libomp.dylib
```

The product does not show you that. It checks before the methodology is
offered, tells you which of the cases below you are in, and names the command
below. The linker error goes to the log, where it is useful.

## macOS

Apple does not ship OpenMP. Install it with Homebrew:

```
brew install libomp
```

Then restart the CreditProbe backend.

## Linux

Most distributions ship it; a slim container image often does not.

```
sudo apt-get install -y libgomp1        # Debian, Ubuntu
sudo dnf install -y libgomp             # Fedora, RHEL
```

Then restart the CreditProbe backend.

## Windows

XGBoost needs the Microsoft Visual C++ runtime, which is not part of a bare
Python installation. Install the **Microsoft Visual C++ Redistributable (x64)**
from Microsoft, then restart the backend.

## Checking it worked

Open **What-If Analysis → Model Configuration → ML Model**. The panel at the
top of that screen reports the platform, the Python version, the XGBoost
version and whether it loaded. It is the same check the methodology gate
consults, so if that panel says available, the gate will offer ML.

Or from the command line:

```
uv run python -c "from backend.whatif.ml import runtime; print(runtime.describe()['message'])"
```

## If you would rather not

Choose the **Delta Model** at the methodology gate. It is the governed
methodology, every figure in it can be reproduced with a calculator, and
choosing it costs you the model comparison and nothing else.

## What the product will never do

Install anything. A product that runs a package manager out of its own request
handler is a product that can change the machine it is running on while
somebody is reading a number off it. The command is printed; a person runs it.
