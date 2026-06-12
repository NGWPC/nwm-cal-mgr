# Installation instructions

Instructions on how to install, configure, and run calibration/validation are given below, 
where [VENV_ROOT] and [NWM_ROOT] refer to the directory to install python venv and nwm-cal-mgr
in your local workspace, respectively.


1. create python venv

```bash
cd [VENV_ROOT]
/usr/bin/python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```
2. clone nwm-cal-mgr from Github

```bash
cd [NWM_ROOT]
git clone -b development https://github.com/NGWPC/nwm-cal-mgr.git
```

3. install **nwm-cal-mgr** package (includes calib, config, and CLI executables)

```bash
cd
pip install [NWM_ROOT]/nwm-cal-mgr # or use flag "-e" to install the package as an editable
```

4. install dependency **mswm**

```bash
cd [NWM_ROOT]
git clone -b development https://github.com/NGWPC/nwm-msw-mgr.git
```

- install mswm
```bash
cd [NWM_ROOT]/nwm-msw-mgr
pip install .
```
5. install dependency **nwm_metrics**

- clone nwm-eval-mgr
```bash
cd [NWM_ROOT]
git clone -b development https://github.com/NGWPC/nwm-eval-mgr.git
```

- install nwm_metrics
```bash
cd [NWM_ROOT]/nwm-eval-mgr/nwm_metrics
pip install .
```