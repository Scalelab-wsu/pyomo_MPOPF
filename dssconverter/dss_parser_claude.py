from __future__ import annotations

from functools import cache
from pathlib import Path
import networkx as nx
import numpy as np
import opendssdirect as dss
import pandas as pd
import re
import os


class DSSParser:
    def __init__(
        self,
        dssfile: (str, Path),
        s_base: float = 1e6,
        v_min: float = 0.95,
        v_max: float = 1.05,
        cvr_p: float = 0,
        cvr_q: float = 0,
    ) -> None:
        self.dss = dss
        self.dssfile = dssfile
        self.dss.Text.Command(f'Redirect "{self.dssfile}"')
        self.dss.Text.Command("Solve")
        self.s_base = s_base
        self.v_min = v_min
        self.v_max = v_max
        self.cvr_p = cvr_p
        self.cvr_q = cvr_q
        self.bus_names = self.get_bus_names()
        self.branch_data = self.get_branch_data()
        self.bus_data = self.get_bus_data()
        self.gen_data = self.get_gen_data()
        self.cap_data = self.get_cap_data()
        self.reg_data = self.get_reg_data()
        self.bat_data = self.get_bat_data()
        self.v_solved = self.get_v_solved()
        self.s_solved = self.get_apparent_power_flows()

    def update(self) -> None:
        self.dss.Solution.Solve()
        self.bus_names = self.get_bus_names()
        self.branch_data = self.get_branch_data()
        self.bus_data = self.get_bus_data()
        self.gen_data = self.get_gen_data()
        self.cap_data = self.get_cap_data()
        self.reg_data = self.get_reg_data()
        self.bat_data = self.get_bat_data()
        self.v_solved = self.get_v_solved()
        self.s_solved = self.get_apparent_power_flows()

    @cache
    def get_bus_names(self) -> list[str]:
        flag = self.dss.PDElements.First()
        branches = []
        while flag:
            element_type = self.dss.CktElement.Name().lower().split(".")[0]
            if element_type not in ["line", "transformer", "reactor"]:
                flag = self.dss.PDElements.Next()
                continue
            if element_type == "line" and self.dss.Lines.IsSwitch():
                switch_status = (
                    "OPEN"
                    if (
                        self.dss.CktElement.IsOpen(1, 0)
                        or self.dss.CktElement.IsOpen(2, 0)
                    )
                    else "CLOSED"
                )
                if switch_status == "OPEN":
                    flag = self.dss.PDElements.Next()
                    continue
            bus1 = self.dss.CktElement.BusNames()[0].split(".")[0]
            bus2 = self.dss.CktElement.BusNames()[1].split(".")[0]
            branches.append((bus1, bus2))
            self.dss.Circuit.SetActiveBus(bus2)
            flag = self.dss.PDElements.Next()

        g = nx.Graph()
        g.add_edges_from(set(branches))
        node_list = list(nx.dfs_preorder_nodes(g, self.source))
        return node_list

    @property
    @cache
    def bus_names_to_index_map(self) -> dict[str, int]:
        _map = {bus: index + 1 for index, bus in enumerate(self.bus_names)}
        return _map

    def bus_names_to_index_map_fun(self, bus: str) -> int:
        return self.bus_names_to_index_map[bus]

    @property
    def basekV_LL(self) -> float:
        self.dss.Circuit.SetActiveBus(self.source)
        return round(self.dss.Bus.kVBase() * np.sqrt(3), 2)

    @property
    def source(self) -> str:
        self.dss.Vsources.First()
        return self.dss.CktElement.BusNames()[0].split(".")[0]

    @property
    def gen_buses(self) -> set[str]:
        flag = self.dss.Generators.First()
        gen_buses = set()
        while flag:
            gen_buses.add(self.dss.Generators.Bus1().split(".")[0])
            flag = self.dss.Generators.Next()
        return gen_buses

    @property
    def bat_buses(self) -> set[str]:
        flag = self.dss.Storages.First()
        bat_buses = set()
        while flag:
            bat_buses.add(self.dss.CktElement.BusNames()[0].split(".")[0])
            flag = self.dss.Storages.Next()
        return bat_buses

    @property
    def cap_buses(self) -> set[str]:
        flag = self.dss.Capacitors.First()
        cap_buses = set()
        while flag:
            cap_buses.add(self.dss.CktElement.BusNames()[0].split(".")[0])
            flag = self.dss.Capacitors.Next()
        return cap_buses

    @property
    def load_buses(self) -> set[str]:
        flag = self.dss.Loads.First()
        load_buses = set()
        while flag:
            load_buses.add(self.dss.CktElement.BusNames()[0].split(".")[0])
            flag = self.dss.Loads.Next()
        return load_buses

    @property
    def num_phase_map(self) -> dict[str, str]:
        num_phase_mapper = {
            "[1]": "a",
            "[2]": "b",
            "[3]": "c",
            "[1, 2]": "ab",
            "[1, 3]": "ac",
            "[2, 3]": "bc",
            "[1, 2, 3]": "abc",
            "[1, 2, 3, 4]": "abc",
        }
        return num_phase_mapper

    # ----------------------------------------------------------------
    # Solved quantities
    # ----------------------------------------------------------------

    def get_v_solved(self) -> pd.DataFrame:
        va = pd.DataFrame({
            "name": [name.split(".")[0] for name in self.dss.Circuit.AllNodeNamesByPhase(1)],
            "a": self.dss.Circuit.AllNodeVmagPUByPhase(1),
        })
        vb = pd.DataFrame({
            "name": [name.split(".")[0] for name in self.dss.Circuit.AllNodeNamesByPhase(2)],
            "b": self.dss.Circuit.AllNodeVmagPUByPhase(2),
        })
        vc = pd.DataFrame({
            "name": [name.split(".")[0] for name in self.dss.Circuit.AllNodeNamesByPhase(3)],
            "c": self.dss.Circuit.AllNodeVmagPUByPhase(3),
        })
        v_df = pd.merge(va, vb, on="name", how="outer")
        v_df = pd.merge(v_df, vc, on="name", how="outer")
        v_df.index = v_df.name.apply(self.bus_names_to_index_map_fun)
        v_df = v_df.sort_index()
        return v_df

    def get_apparent_power_flows(self) -> pd.DataFrame:
        flag = self.dss.PDElements.First()
        power_data = []
        while flag:
            element_type = self.dss.CktElement.Name().lower().split(".")[0]
            is_open = [
                self.dss.CktElement.IsOpen(0, ph)
                for ph in range(self.dss.CktElement.NumPhases())
            ]
            if all(is_open):
                flag = self.dss.PDElements.Next()
                continue
            if element_type not in ["line", "transformer", "reactor"]:
                flag = self.dss.PDElements.Next()
                continue

            s_out = self._get_powers() * 1000 / self.s_base
            bus1 = self.dss.CktElement.BusNames()[0].split(".")[0]
            bus2 = self.dss.CktElement.BusNames()[1].split(".")[0]
            self.dss.Circuit.SetActiveBus(bus2)

            each_power = dict(
                fb=self.bus_names_to_index_map[bus1],
                tb=self.bus_names_to_index_map[bus2],
                from_name=bus1,
                to_name=bus2,
                a=s_out[0],
                b=s_out[1],
                c=s_out[2],
            )
            power_data.append(each_power)
            flag = self.dss.PDElements.Next()

        power_df = pd.DataFrame(power_data)
        power_df.fb = power_df.fb.astype(int)
        power_df.tb = power_df.tb.astype(int)
        power_df = (
            power_df.groupby(by=["fb", "tb"], as_index=False)
            .agg({"fb": "first", "tb": "first", "from_name": "first",
                  "to_name": "first", "a": "sum", "b": "sum", "c": "sum"})
            .reset_index(drop=True)
            .sort_values(by=["fb"], ignore_index=True)
            .sort_values(by=["tb"], ignore_index=True)
        )
        return power_df

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    def _get_line_zmatrix(self) -> tuple[np.ndarray, np.ndarray]:
        bus_parts = self.dss.CktElement.BusNames()[0].split(".")
        n_phases = self.dss.Lines.Phases()
        z_matrix_real = np.zeros((3, 3))
        z_matrix_imag = np.zeros((3, 3))

        if n_phases == 3 or len(bus_parts) in (1, 4, 5):
            z_matrix = (
                np.array(self.dss.Lines.RMatrix())
                + 1j * np.array(self.dss.Lines.XMatrix())
            ) * self.dss.Lines.Length()
            z_matrix = z_matrix.reshape(3, 3)
            return np.real(z_matrix), np.imag(z_matrix)
        else:
            active_phases = [int(p) for p in bus_parts[1:]]
            r_matrix = self.dss.Lines.RMatrix()
            x_matrix = self.dss.Lines.XMatrix()
            counter = 0
            for row in active_phases:
                for col in active_phases:
                    z_matrix_real[row - 1, col - 1] = r_matrix[counter] * self.dss.Lines.Length()
                    z_matrix_imag[row - 1, col - 1] = x_matrix[counter] * self.dss.Lines.Length()
                    counter += 1
            return z_matrix_real, z_matrix_imag

    def _get_reactor_zmatrix(self) -> tuple[np.ndarray, np.ndarray]:
        n_phases = self.dss.Reactors.Phases()
        if n_phases == 3:
            return np.eye(3) * self.dss.Reactors.R(), np.eye(3) * self.dss.Reactors.X()
        else:
            raise NotImplementedError(
                "Parsing reactors with phases other than 3 not implemented"
            )

    def _get_transformer_zmatrix(self, active_phases: list[int]) -> tuple[np.ndarray, np.ndarray]:
        z_matrix_real = np.zeros((3, 3))
        z_matrix_imag = np.zeros((3, 3))

        # LV side impedance base
        self.dss.Transformers.Wdg(2)
        kv_l     = self.dss.Transformers.kV()
        is_delta = self.dss.Transformers.IsDelta()

        if is_delta:
            v_base_xfmr = kv_l * 1000
        else:
            v_base_xfmr = kv_l / np.sqrt(3) * 1000

        s_base_xfmr = self.dss.Transformers.kVA() * 1000 / 3
        z_base_xfmr = v_base_xfmr ** 2 / s_base_xfmr

        # FIX: removed the erroneous * 2 on r_xfmr
        r_xfmr = self.dss.Transformers.R()   / 100.0 * z_base_xfmr
        x_xfmr = self.dss.Transformers.Xhl() / 100.0 * z_base_xfmr

        for ph in active_phases:
            z_matrix_real[ph, ph] = r_xfmr
            z_matrix_imag[ph, ph] = x_xfmr

        return z_matrix_real, z_matrix_imag

    def _get_powers(self) -> np.ndarray:
        n_phases   = self.dss.CktElement.NumPhases()
        pq         = np.array(self.dss.CktElement.Powers())
        n_terminals = self.dss.CktElement.NumTerminals()
        n_pq_phases = len(pq) // n_terminals // 2
        pq          = pq.reshape(int(n_pq_phases * n_terminals), 2)
        s_out       = np.zeros(3, dtype=complex)
        active_phases = np.array([0, 1, 2])
        if n_phases < 3:
            active_phases = (
                np.array(self.dss.CktElement.BusNames()[0].split(".")[1:]).astype(int) - 1
            )
        p = pq[:, 0]
        q = pq[:, 1]
        s = p + 1j * q
        s_out_ = -s[n_pq_phases:]
        s_out[active_phases] = s_out_[:n_phases]
        return s_out

    # ----------------------------------------------------------------
    # Branch data
    # ----------------------------------------------------------------

    def get_branch_data(self) -> pd.DataFrame:
        s_base = self.s_base
        flag   = self.dss.PDElements.First()
        line_data = []

        while flag:
            switch_status = None
            element_type  = self.dss.CktElement.Name().lower().split(".")[0]
            element_name  = self.dss.CktElement.Name().lower().split(".")[1]
            z_matrix_real = np.zeros((3, 3))
            z_matrix_imag = np.zeros((3, 3))

            if element_type not in ["line", "transformer", "reactor"]:
                flag = self.dss.PDElements.Next()
                continue

            # FIX: extract phases BEFORE any bus swap
            bus_parts_0 = self.dss.CktElement.BusNames()[0].split(".")
            n_phases    = self.dss.CktElement.NumPhases()
            if n_phases == 3 or len(bus_parts_0) == 1:
                active_phases = [0, 1, 2]
                phases        = "abc"
            else:
                active_phases = [int(p) - 1 for p in bus_parts_0[1:]]
                phases        = "".join("abc"[i] for i in active_phases)

            if element_type == "transformer":
                element_name  = self.dss.Transformers.Name()
                z_matrix_real, z_matrix_imag = self._get_transformer_zmatrix(active_phases)

            elif element_type == "line":
                element_name  = self.dss.Lines.Name()
                z_matrix_real, z_matrix_imag = self._get_line_zmatrix()
                if self.dss.Lines.IsSwitch():
                    element_type  = "switch"
                    switch_status = (
                        "OPEN"
                        if (
                            self.dss.CktElement.IsOpen(1, 0)
                            or self.dss.CktElement.IsOpen(2, 0)
                        )
                        else "CLOSED"
                    )

            elif element_type == "reactor":
                element_name  = self.dss.Reactors.Name()
                z_matrix_real, z_matrix_imag = self._get_reactor_zmatrix()

            # FIX: compare integer indices not strings for bus swap
            bus1 = self.dss.CktElement.BusNames()[0].split(".")[0]
            bus2 = self.dss.CktElement.BusNames()[1].split(".")[0]
            fb   = self.bus_names_to_index_map[bus1]
            tb   = self.bus_names_to_index_map[bus2]

            if fb > tb:
                fb, tb     = tb, fb
                bus1, bus2 = bus2, bus1

            self.dss.Circuit.SetActiveBus(bus2)
            base_kv_ln = self.dss.Bus.kVBase()
            z_base     = (base_kv_ln * 1000) ** 2 / s_base

            each_line = dict(
                fb=fb,
                tb=tb,
                from_name=bus1,
                to_name=bus2,
                raa=z_matrix_real[0, 0] / z_base,
                rab=z_matrix_real[0, 1] / z_base,
                rac=z_matrix_real[0, 2] / z_base,
                rbb=z_matrix_real[1, 1] / z_base,
                rbc=z_matrix_real[1, 2] / z_base,
                rcc=z_matrix_real[2, 2] / z_base,
                xaa=z_matrix_imag[0, 0] / z_base,
                xab=z_matrix_imag[0, 1] / z_base,
                xac=z_matrix_imag[0, 2] / z_base,
                xbb=z_matrix_imag[1, 1] / z_base,
                xbc=z_matrix_imag[1, 2] / z_base,
                xcc=z_matrix_imag[2, 2] / z_base,
                type=element_type,
                name=element_name,
                status=switch_status,
                s_base=s_base,
                v_ln_base=base_kv_ln * 1000,
                z_base=z_base,
                phases=phases,
            )
            line_data.append(each_line)
            flag = self.dss.PDElements.Next()

        branch_df = pd.DataFrame(line_data)
        branch_df = (
            branch_df.groupby(by=["fb", "tb"], as_index=False)
            .agg({
                "fb": "max", "tb": "max",
                "from_name": "first", "to_name": "first",
                "raa": "sum", "rab": "sum", "rac": "sum",
                "rbb": "sum", "rbc": "sum", "rcc": "sum",
                "xaa": "sum", "xab": "sum", "xac": "sum",
                "xbb": "sum", "xbc": "sum", "xcc": "sum",
                "type": "first", "name": "first", "status": "first",
                "s_base": "first", "v_ln_base": "first", "z_base": "first",
                "phases": "sum",
            })
            .sort_values(by=["tb", "fb"], ignore_index=True)
            .reset_index(drop=True)
        )
        return branch_df

    # ----------------------------------------------------------------
    # Bus data
    # ----------------------------------------------------------------

    def get_bus_data(self) -> pd.DataFrame:
        source_voltage = self.dss.Vsources.PU()
        s_base  = self.s_base
        v_min   = self.v_min
        v_max   = self.v_max
        cvr_p   = self.cvr_p
        cvr_q   = self.cvr_q
        all_buses_names = self.dss.Circuit.AllBusNames()
        load_df = self.get_loads()
        bus_data = []

        for busid, bus in enumerate(all_buses_names):
            self.dss.Circuit.SetActiveBus(bus)
            bus_type = "PQ"
            v = 1
            if (
                len(self.dss.Bus.AllPCEatBus()) > 0
                and "Vsource" in self.dss.Bus.AllPCEatBus()[0]
            ):
                v        = source_voltage
                bus_type = "SWING"

            active_bus_name = self.dss.Bus.Name()
            vln_base        = self.dss.Bus.kVBase() * 1000

            each_bus = dict(
                id=self.bus_names_to_index_map[bus],
                name=active_bus_name,
                bus_type=bus_type,
                v_a=v, v_b=v, v_c=v,
                vln_base=vln_base,
                s_base=s_base,
                v_min=v_min,
                v_max=v_max,
                cvr_p=cvr_p,
                cvr_q=cvr_q,
                phases=self.num_phase_map[str(self.dss.Bus.Nodes())],
                has_gen=True if active_bus_name in self.gen_buses else False,
                has_load=True if active_bus_name in self.load_buses else False,
                has_cap=True if active_bus_name in self.cap_buses else False,
                latitude=self.dss.Bus.Y(),
                longitude=self.dss.Bus.X(),
            )
            bus_data.append(each_bus)

        bus_df = pd.DataFrame(bus_data)
        bus_df = (
            pd.merge(load_df, bus_df, on="id", how="outer")
            .sort_values(by="id", ignore_index=True)
            .fillna(0)
        )
        return bus_df

    # ----------------------------------------------------------------
    # Generator data
    # ----------------------------------------------------------------

    def get_gen_data(self) -> pd.DataFrame:
        s_base = self.s_base
        gen_data = []

        generator_flag = self.dss.Generators.First()
        while generator_flag:
            bus_phases = self.dss.CktElement.BusNames()[0].split(".")[1:]
            n_phases   = len(bus_phases)
            if n_phases == 0 or n_phases == 3:
                n_phases      = 3
                active_phases = np.array([0, 1, 2])
            else:
                active_phases = np.array(self.dss.CktElement.BusNames()[0].split(".")[1:]).astype(int) - 1

            active_power_per_phase   = self.dss.Generators.kW()   / n_phases / 1000 / s_base
            reactive_power_per_phase = self.dss.Generators.kvar() / n_phases / 1000 / s_base
            apparent_power_rating    = self.dss.Generators.kVARated() / n_phases / 1000 / s_base
            gen_name  = self.dss.Generators.Name()
            bus_name  = self.dss.Generators.Bus1().split(".")[0]

            each_gen = dict(
                id=self.bus_names_to_index_map[bus_name],
                name=gen_name,
                bus=bus_name,
            )
            phases = ""
            for phase_id in active_phases:
                ph = "abc"[phase_id]
                each_gen[f"p{ph}"] = active_power_per_phase
                each_gen[f"q{ph}"] = reactive_power_per_phase
                each_gen[f"s{ph}_max"] = apparent_power_rating
                phases += ph
            for ph in "abc":
                if ph not in phases:
                    each_gen[f"p{ph}"]     = 0
                    each_gen[f"q{ph}"]     = 0
                    each_gen[f"s{ph}_max"] = 0
            each_gen["phases"]  = phases
            each_gen.update({
                "qamax": None, "qbmax": None, "qcmax": None,
                "qamin": None, "qbmin": None, "qcmin": None,
            })
            gen_data.append(each_gen)
            generator_flag = self.dss.Generators.Next()

        pv_flag = self.dss.PVsystems.First()
        while pv_flag:
            bus_phases = self.dss.CktElement.BusNames()[0].split(".")[1:]
            n_phases   = len(bus_phases)
            if n_phases == 0 or n_phases == 3:
                n_phases      = 3
                active_phases = np.array([0, 1, 2])
            else:
                active_phases = np.array(self.dss.CktElement.BusNames()[0].split(".")[1:]).astype(int) - 1

            active_power_per_phase   = self.dss.PVsystems.Pmpp()     / n_phases / 1000 / s_base
            reactive_power_per_phase = self.dss.PVsystems.kvar()     / n_phases / 1000 / s_base
            apparent_power_rating    = self.dss.PVsystems.kVARated() / n_phases / 1000 / s_base
            bus_name = self.dss.CktElement.BusNames()[0].split(".")[0]

            each_gen = dict(
                id=self.bus_names_to_index_map[bus_name],
                name=bus_name,
                bus=bus_name,
            )
            phases = ""
            for phase_id in active_phases:
                ph = "abc"[phase_id]
                each_gen[f"p{ph}"] = active_power_per_phase
                each_gen[f"q{ph}"] = reactive_power_per_phase
                each_gen[f"s{ph}_max"] = apparent_power_rating
                phases += ph
            for ph in "abc":
                if ph not in phases:
                    each_gen[f"p{ph}"]     = 0
                    each_gen[f"q{ph}"]     = 0
                    each_gen[f"s{ph}_max"] = 0
            each_gen["phases"]  = phases
            each_gen.update({
                "qamax": None, "qbmax": None, "qcmax": None,
                "qamin": None, "qbmin": None, "qcmin": None,
            })
            gen_data.append(each_gen)
            pv_flag = self.dss.PVsystems.Next()

        gen_df = pd.DataFrame(gen_data)
        if len(gen_data) < 1:
            gen_df = pd.DataFrame(columns=[
                'id','name','pa','pb','pc','qa','qb','qc',
                'sa_max','sb_max','sc_max','phases',
                'qamax','qbmax','qcmax','qamin','qbmin','qcmin',
            ])
        else:
            gen_df = (
                gen_df.groupby(by=["id"], as_index=False)
                .agg(dict(
                    id="first", name="first", bus="first",
                    pa="sum", pb="sum", pc="sum",
                    qa="sum", qb="sum", qc="sum",
                    sa_max="sum", sb_max="sum", sc_max="sum",
                    phases="sum",
                    qamax="sum", qbmax="sum", qcmax="sum",
                    qamin="sum", qbmin="sum", qcmin="sum",
                ))
            )
        return gen_df

    # ----------------------------------------------------------------
    # Battery data
    # ----------------------------------------------------------------

    def get_bat_data(self) -> pd.DataFrame:
        sbase = self.s_base

        if self.dss.Storages.Count() == 0:
            return pd.DataFrame()

        storage_df = self.dss.utils.class_to_dataframe("Storage")
        storage_df.columns = storage_df.columns.str.lower()

        bat_data = []

        for elem_name, row in storage_df.iterrows():
            bus_parts   = str(row['bus1']).split('.')
            bus_name    = bus_parts[0].lower()
            n_phases    = int(row['phases'])

            if n_phases == 3 or len(bus_parts) == 1:
                active_phases = [0, 1, 2]
            else:
                active_phases = [int(p) - 1 for p in bus_parts[1:]]

            kw_rated  = float(row['kwrated'])
            kwh_rated = float(row['kwhrated'])
            eff_c     = float(row['%effcharge'])    / 100.0
            eff_d     = float(row['%effdischarge']) / 100.0
            pct_res   = float(row['%reserve'])      / 100.0

            each_bat = {
                "id":   self.bus_names_to_index_map[bus_name],
                "name": bus_name,
            }
            phases = ""
            for ph_idx in active_phases:
                ph = "abc"[ph_idx]
                each_bat[f"Pb_max_{ph}"] = (kw_rated  / n_phases) / 1000 / sbase * 1e6
                each_bat[f"hmax_{ph}"]   = (kw_rated  / n_phases) / 1000 / sbase * 1e6
                each_bat[f"bmin_{ph}"]   = pct_res * (kwh_rated / n_phases) / 1000 / sbase * 1e6
                each_bat[f"bmax_{ph}"]   = 0.95    * (kwh_rated / n_phases) / 1000 / sbase * 1e6
                each_bat[f"nc_{ph}"]     = eff_c
                each_bat[f"nd_{ph}"]     = eff_d
                phases                  += ph

            for ph in "abc":
                if ph not in phases:
                    for key in ["Pb_max", "hmax", "bmin", "bmax", "nc", "nd"]:
                        each_bat[f"{key}_{ph}"] = 0.0

            each_bat["phases"] = phases
            bat_data.append(each_bat)

        if len(bat_data) == 0:
            return pd.DataFrame()

        bat_df = pd.DataFrame(bat_data)
        bat_df = (
            bat_df.groupby("id", as_index=False)
            .agg({col: "sum" if col != "name" else "first"
                  for col in bat_df.columns})
            .sort_values("id", ignore_index=True)
        )
        return bat_df

    # ----------------------------------------------------------------
    # Capacitor data
    # ----------------------------------------------------------------

    def get_cap_data(self) -> pd.DataFrame:
        s_base  = self.s_base
        flag    = self.dss.Capacitors.First()
        cap_data = []
        while flag:
            cap_bus_name   = self.dss.CktElement.BusNames()[0].split(".")[0]
            cap_bus_phases = self.dss.CktElement.BusNames()[0].split(".")[1:]
            cap_bus_phases = cap_bus_phases if cap_bus_phases else ["1", "2", "3"]
            cap_phase      = self.num_phase_map[str([int(p) for p in cap_bus_phases])]

            if cap_phase != "abc":
                each_cap = dict(
                    id=self.bus_names_to_index_map[cap_bus_name],
                    name=cap_bus_name,
                    qa=self.dss.Capacitors.kvar() / 1000 / s_base if "a" in cap_phase else 0,
                    qb=self.dss.Capacitors.kvar() / 1000 / s_base if "b" in cap_phase else 0,
                    qc=self.dss.Capacitors.kvar() / 1000 / s_base if "c" in cap_phase else 0,
                    phases=cap_phase,
                )
            else:
                each_cap = dict(
                    id=self.bus_names_to_index_map[cap_bus_name],
                    name=cap_bus_name,
                    qa=self.dss.Capacitors.kvar() / 1000 / 3 / s_base,
                    qb=self.dss.Capacitors.kvar() / 1000 / 3 / s_base,
                    qc=self.dss.Capacitors.kvar() / 1000 / 3 / s_base,
                    phases=cap_phase,
                )
            cap_data.append(each_cap)
            flag = self.dss.Capacitors.Next()

        cap_df = pd.DataFrame(cap_data)
        if len(cap_data) < 1:
            cap_df = pd.DataFrame(columns=['id','name','qa','qb','qc','phases'])
        else:
            cap_df = (
                cap_df.groupby(by=["id"], as_index=False)
                .agg(dict(id="first", name="first", qa="sum", qb="sum", qc="sum", phases="sum"))
            )
        return cap_df

    # ----------------------------------------------------------------
    # Regulator data
    # ----------------------------------------------------------------

    def get_reg_data(self) -> pd.DataFrame:
        s_base = self.s_base
        reg_data = []
        reg_control_names = self.dss.RegControls.AllNames()
        reg_names = []

        if len(reg_control_names) != 0:
            dss_reg_df  = self.dss.utils.regcontrols_to_dataframe()
            dss_reg_df.columns = dss_reg_df.columns.str.lower()
            reg_names   = dss_reg_df['transformer'].tolist()

        flag = self.dss.Transformers.First()
        while flag:
            element_type = self.dss.CktElement.Name().lower().split(".")[0]
            element_name = self.dss.CktElement.Name().lower().split(".")[1]

            if element_type not in ["transformer"]:
                flag = self.dss.Transformers.Next()
                continue
            if element_name not in reg_names:
                flag = self.dss.Transformers.Next()
                continue

            bus1 = self.dss.CktElement.BusNames()[0].split(".")[0]
            bus2 = self.dss.CktElement.BusNames()[-1].split(".")[0]
            fb   = self.bus_names_to_index_map[bus1]
            tb   = self.bus_names_to_index_map[bus2]

            tap_direction = 1
            if fb > tb:
                fb, tb     = tb, fb
                bus1, bus2 = bus2, bus1
                tap_direction = -1

            self.dss.Circuit.SetActiveBus(bus2)

            # FIX: extract phases before swap has no effect here since
            # BusNames()[0] is always the original bus1 from DSS
            line_phases = self.dss.CktElement.BusNames()[0].split(".")[1:]
            line_phases = sorted(line_phases)
            line_phase  = self.num_phase_map[str([int(p) for p in line_phases])] if line_phases else "abc"

            ratio = self.dss.Transformers.Tap()
            tap   = (ratio - 1) / 0.00625

            each_reg = {
                "fb":        fb,
                "tb":        tb,
                "from_name": bus1,
                "to_name":   bus2,
                "tap_a":     0,
                "tap_b":     0,
                "tap_c":     0,
                "phases":    line_phase,
            }
            for ph in line_phase:
                each_reg[f"tap_{ph}"] = int(round(tap))

            reg_data.append(each_reg)
            flag = self.dss.Transformers.Next()

        reg_df = pd.DataFrame(reg_data)
        if len(reg_data) < 1:
            reg_df = pd.DataFrame(columns=['fb','tb','from_name','to_name','tap_a','tap_b','tap_c','phases'])
        else:
            reg_df = (
                reg_df.groupby(["fb", "tb"])
                .agg({
                    "fb": "first", "tb": "first",
                    "from_name": "first", "to_name": "first",
                    "tap_a": "max", "tap_b": "max", "tap_c": "max",
                    "phases": "sum",
                })
                .reset_index(drop=True)
                .sort_values(by="tb", ignore_index=True)
                .fillna(1)
            )
        return reg_df

    # ----------------------------------------------------------------
    # Load data
    # ----------------------------------------------------------------

    def get_loads(self) -> pd.DataFrame:
        s_base   = self.s_base
        load_df  = pd.DataFrame(columns=['id','name','pl_a','ql_a','pl_b','ql_b','pl_c','ql_c'])
        loads_flag = self.dss.Loads.First()
        load_data  = []

        model_to_cvr_map = {
            1: (0, 0), 2: (2, 2), 3: (0, 2),
            5: (1, 1), 6: (0, 0), 7: (0, 2),
        }

        while loads_flag:
            connected_buses = self.dss.CktElement.BusNames()
            if len(connected_buses) > 1:
                raise Exception("Multiple connected buses")

            model      = self.dss.Loads.Model()
            cvr_p, cvr_q = model_to_cvr_map.get(model, (0, 0))
            if model == 4:
                cvr_p = self.dss.Loads.CVRwatts()
                cvr_q = self.dss.Loads.CVRvars()
            if model == 8:
                zip_v = self.dss.Loads.ZipV()
                cvr_p = 2 * zip_v[0] + zip_v[1]
                cvr_q = 2 * zip_v[3] + zip_v[4]

            bus        = connected_buses[0]
            bus_name   = bus.split(".")[0]
            bus_split  = bus.split(".")

            each_load = {
                "id": 0, "pl_a": 0, "ql_a": 0,
                "pl_b": 0, "ql_b": 0, "pl_c": 0, "ql_c": 0,
                "cvr_p": cvr_p, "cvr_q": cvr_q,
            }
            each_load["id"] = self.bus_names_to_index_map[bus_name]

            connected_phase_secondary = bus_split[1] if len(bus_split) > 1 else None
            n_phases   = self.dss.Loads.Phases()
            pf         = self.dss.Loads.PF()
            kw         = self.dss.Loads.kW()
            kvar       = self.dss.Loads.kvar()
            is_delta   = self.dss.Loads.IsDelta()

            conductor_power = np.array(self.dss.CktElement.Powers())
            p_values = conductor_power[0::2]
            q_values = conductor_power[1::2]

            if connected_phase_secondary:
                phases = "".join("abc"[int(n) - 1] for n in bus_split[1:])
            else:
                phases = "abc"

            for phase_index, ph in enumerate(phases):
                each_load[f"pl_{ph}"] = p_values[phase_index] / 1000 / s_base
                each_load[f"ql_{ph}"] = q_values[phase_index] / 1000 / s_base

            load_data.append(each_load)
            loads_flag = self.dss.Loads.Next()

        load_df = pd.DataFrame(load_data)
        load_df = (
            load_df.groupby("id")
            .agg({"id": "first", "pl_a": "sum", "ql_a": "sum",
                  "pl_b": "sum", "ql_b": "sum", "pl_c": "sum", "ql_c": "sum"})
            .fillna(0)
            .reset_index(drop=True)
        )
        return load_df

    # ----------------------------------------------------------------
    # Export
    # ----------------------------------------------------------------

    def to_csv(self, dirname: str = None, overwrite: bool = True) -> None:
        if dirname is None:
            dirname = "testfiles"
        Path(dirname).mkdir(parents=True, exist_ok=overwrite)
        self.branch_data.to_csv(f"{dirname}/branch_data.csv", index=False)
        self.bus_data.to_csv(f"{dirname}/bus_data.csv",       index=False)
        self.cap_data.to_csv(f"{dirname}/cap_data.csv",       index=False)
        self.gen_data.to_csv(f"{dirname}/gen_data.csv",       index=False)
        self.reg_data.to_csv(f"{dirname}/reg_data.csv",       index=False)
        self.bat_data.to_csv(f"{dirname}/bat_data.csv",       index=False)