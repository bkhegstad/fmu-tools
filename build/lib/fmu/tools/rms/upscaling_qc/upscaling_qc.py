from pathlib import Path
from typing import List, Union, Dict, Set
from dataclasses import asdict
import json
from unittest import result
import xtgeo

import pandas as pd
from fmu.tools.qcproperties._grid2df import GridProps2df
from fmu.tools.qcproperties._well2df import WellLogs2df
from fmu.tools.qcdata import QCData

from fmu.tools.rms.upscaling_qc._types import (
    WellContext,
    GridContext,
    BlockedWellContext,
    UpscalingQCFiles,
    GridMetaData,
    BWMetaData,
    WellMetaData,
    MetaData,
    DefaultDisplayNames,
)


class RMSUpscalingQC:
    def __init__(
        self, project, data: dict
    ) -> None:
        self._project = project

        #Extract data from input definition dictionary
        self._well_data = []
        for i, elem in enumerate(data["wells"]):
            self._well_data.append(WellContext.from_dict(elem))
        
        self._grid_data = []
        for i, elem in enumerate(data["grid"]):    
            self._grid_data.append(GridContext.from_dict(elem))
        #print(self._grid_data)

        self._bw_data = []
        for i, elem in enumerate(data["blockedwells"]):
            self._bw_data.append(BlockedWellContext.from_dict(elem))

        #Validate if input is consistent
        self._validate_grid_names()
        self._validate_properties()
        self._validate_selectors()
        self._validate_bw_grid_names()
        self._validate_well_names()
        
        #Get the names of the wells. This is needed when data is extracted.
        self._set_well_names()

        self._zone_names = self._get_zone_names()

    def _set_well_names(self) -> None:
        '''
        Populates the internal model definition with wells to use
        Well names are the wells defined by self._well_names
             names-entry if defined (must be identical for all "wells" and "blockedwells" entires or
             all wells defined by the blocked wells
        '''
        well_names = self._well_names 
        for i in range(len(self._well_data)):
            self._well_data[i].wells.names = well_names[:]

        for i in range(len(self._bw_data)):
            self._bw_data[i].wells.names = well_names[:]


    def _validate_well_names(self) -> None:
        well_names = []
        for w in self._well_data + self._bw_data:
                well_names.append(w.wells.names)
        for i in range(len(well_names)-1):
            if set(well_names[i]) != set(well_names[i+1]):
                print(f"Defined wells to report: {well_names}")
                raise ValueError(f"The wells to report should be identical for all wells and blocked wells instances")

 
    def _validate_grid_names(self) -> None:
        #Get all gridnames from bw_wells
        gridname_from_bw = []
        for i in range(len(self._bw_data)):
            gridname_from_bw.append(self._bw_data[i].wells.grid)

        gridname_from_grid = []
        for i in range(len(self._grid_data)):
            gridname_from_grid.append(self._grid_data[i].grid)
            
        print(f"Grid origin for blocked wells: {gridname_from_bw}")
        print(f"Grids for statistics: {gridname_from_grid}")
        if set(gridname_from_bw) != set(gridname_from_grid):
            raise ValueError("Different grids given for blocked wells and grid.")
        print("Selected grids vs selected BW OK")

    def _validate_bw_grid_names(self) -> None:
        #Check if the bw-names actually exists for each of the grids
        for bw in self._bw_data:
            grid_name = bw.wells.grid
            bwname = bw.wells.bwname
            grid = self._project.grid_models[grid_name]
            if bwname not in grid.blocked_wells_set:
                print(f'The blocked well "{bwname}" does not exist for "{grid_name}"')
                print("Check your definitions")
                raise ValueError("The blocked wells seems not to exist")
        print("Blocked wells names OK")


    def _validate_properties(self) -> None:
        all_elems = []
        for elem in self._well_data:
            all_elems.append(self._to_set(elem.properties))
        for elem in self._bw_data:
            all_elems.append(self._to_set(elem.properties))
        for elem in self._grid_data:
            all_elems.append(self._to_set(elem.properties))

        #Comparing each pair. Raise error for the first pair that fails
        for i in range(len(all_elems) -1):
            if not all_elems[i] == all_elems[i+1]:
                raise ValueError("Data sources do not have the same properties!")
        print("Properties OK")

    def _validate_selectors(self) -> None:
        all_elems = []
        for elem in self._well_data:
            all_elems.append(self._to_set(elem.selectors))
        for elem in self._bw_data:
            all_elems.append(self._to_set(elem.selectors))
        for elem in self._grid_data:
            all_elems.append(self._to_set(elem.selectors))

        #Comparing each pair. Raise error for the first pair that fails
        for i in range(len(all_elems) -1):
            if not all_elems[i] == all_elems[i+1]:
                raise ValueError("Data sources do not have the same selectors!")
        print("Selectors OK")

    @staticmethod
    def _to_set(values: Union[List, Dict]) -> Set[str]:
        if isinstance(values, list):
            return set(values)
        return set(list(values.keys()))

    @property
    def _selectors(self) -> List[str]:
        if isinstance(self._well_data[0].selectors, list):
            return self._well_data[0].selectors
        return list(self._well_data[0].selectors.keys())

    @property
    def _properties(self) -> List[str]:
        if isinstance(self._well_data[0].properties, list):
            return self._well_data[0].properties
        return list(self._well_data[0].properties.keys())

    @property
    def _metadata(self) -> MetaData:
        return MetaData(
            selectors=self._selectors,
            properties=self._properties,
            well_names=self._well_names,
            raw_log_names=self._raw_log_names,
            bw_names = self._bw_names,
            grid_names = self._grid_names,
            selector_values_sorted = self._selector_values_sorted,
        )

    @property
    def _well_names(self) -> List[str]:
        '''
        Returns defined wells as defined in the "names"-entries - or if not defined: 
           all wells used in defining the blocked wells
           Needed since names are default set to [] in WellContext
        '''
        try:
            well_names = []
            for w in self._well_data + self._bw_data:
                if len(w.wells.names) > 0:
                    well_names.append(w.wells.names)        
            if len(well_names) == 0: #If no names-entries are found
                for bw in self._bw_data:
                    grid_name = bw.wells.grid
                    grid = self._project.grid_models[grid_name]
                    well_names.append(grid.blocked_wells_set[bw.wells.bwname].get_well_names())

            if len(well_names) > 0:
                well_names = [item for sublist in well_names for item in sublist]  #Flatten the list
                return list(set(well_names))
            else:
                raise ValueError

        except ValueError:
            print("WARNING: No wells found")
            return []

    @property
    def _raw_log_names(self) -> List[WellMetaData]:
        '''Returns all raw log (trajectoty/logrun)-pairs'''
        names = []
        n = len(self._well_data)
        for well in self._well_data:
            logrun = well.wells.logrun
            trajectory = well.wells.trajectory
            display_name = DefaultDisplayNames.WELLS
            if n > 1:
                display_name += f"_{logrun}"
            names.append(WellMetaData(
                logrun=logrun,
                trajectory =  trajectory,
                display_name = display_name
                )
            )
        return names

    @property
    def _bw_names(self) -> List[BWMetaData]:
        '''Returns all bw names defined and corresponding grids
           Only used in metadata '''
        names = []
        n_bw = len(self._bw_data)
        n_grid = len(self._grid_data)
        for bw in self._bw_data:
            grid_name = bw.wells.grid
            bw_name = bw.wells.bwname
            if n_bw==1:
                display_name = DefaultDisplayNames.BLOCKEDWELLS
            else:
                if n_grid ==1:
                    display_name = bw_name
                else:
                    display_name = f"{bw_name}-{grid_name}"
            names.append(BWMetaData(
                name = bw_name, 
                grid = grid_name,
                display_name = display_name
                )
            )
        return names

    @property
    def _grid_names(self) -> List[GridMetaData]:
        '''Returns all grid names defined. 
           Only used in metadata '''
        names = []
        n = len(self._grid_data)
        for grid in self._grid_data:
            grid_name = grid.grid
            if n== 1:
                display_name = DefaultDisplayNames.GRID
            else:
                display_name = grid_name
            names.append( GridMetaData(
                name = grid_name,
                display_name = display_name
                )
            )  
        return names 

    @property
    def _selector_values_sorted(self) -> dict:
        '''Gets the order of the selectors as defined in wells (raw logs)
           Only used in metadata '''
        result= {}
        for selector in self._well_data[0].selectors:
            try:
                codes = self._well_data[0].selectors[selector]["codes"]
                #print(codes)
                codes_no = sorted(list(codes.keys()))
                ordered_selector_codes = [codes[i] for i in codes_no]

                #Remove potential duplicates with zones where raw logs are merged
                ordered_selector_codes = pd.Series(ordered_selector_codes).drop_duplicates().tolist()
                print(ordered_selector_codes)
                result[selector] = ordered_selector_codes[:]
                #print(ordered_selectors)
            except:
                print(f"Warning: No coding for {selector} is given for raw logs. Hence order {selector} is unknown")
                result[selector] = []
        return result
        
    def _get_zone_names(self) -> dict:
        '''Not used yet - but this is a way to get the order of the zones directly from the grids'''
        zone_names = {}
        for i, elem in enumerate(self._grid_data):
            name = elem.grid
            mygrid = xtgeo.grid_from_roxar(self._project, name)
            zone_names[name] = list(mygrid.subgrids.keys())

        return zone_names


    def _get_well_data(self) -> pd.DataFrame:
        #Extracts raw log data
        dfs = []
        for i, elem in enumerate(self._well_data):
            print(f'Extracting data from raw logs: logrun: "{elem.wells.logrun}", trajecory: "{elem.wells.trajectory}"')
            df = WellLogs2df(
                project=self._project, 
                data=asdict(elem), 
                xtgdata=QCData()
            ).dataframe.copy()
            #There must be a better way to do this? Want to make sure that
            #the headers in the data-file is the same as the entry in the metadata
            if hasattr(WellMetaData, "logrun") and hasattr(WellMetaData, "trajectory"):            
                df['logrun'] = elem.wells.logrun
                df['trajectory'] = elem.wells.trajectory
                dfs.append(df)      
            else:
                raise ValueError("upscaling qc has become out of sync with metadata from fmu-tools")
        return pd.concat(dfs) 

    def _get_bw_data(self) -> pd.DataFrame:
        #Extracts blocked wells log-data
        dfs = []
        print("Extracting data from blocked wells")
        for i, elem in enumerate(self._bw_data):
            print(f"   {elem.wells.bwname} <-- {elem.wells.grid}")
            df = WellLogs2df(
                    project=self._project,
                    data=asdict(elem),
                    xtgdata=QCData(),
                    blockedwells=True,
            ).dataframe.copy()
            #There must be a better way to do this? Want to make sure that
            #the headers in the data-file is the same as the entry in the metadata
            if hasattr(BWMetaData, "grid") and hasattr(BWMetaData, "name"):
                df['grid'] = elem.wells.grid
                df['name'] = elem.wells.bwname
                dfs.append(df)            
            else:
                raise ValueError("upscaling qc has become out of sync with metadata from fmu-tools")
        return pd.concat(dfs)

    def _get_grid_data(self) -> pd.DataFrame:
        dfs = []
        print("Extracting data from grids")
        for i, elem in enumerate(self._grid_data):
            print(f"    {elem.grid} ")
            df = GridProps2df(
                    project=self._project, 
                    data=asdict(elem),
                    xtgdata=QCData()
            ).dataframe.copy()
            #There must be a better way to do this? Want to make sure that
            #the headers in the data-file is the same as the entry in the metadata           
            if hasattr(GridMetaData, "name"):              
                df["name"] = elem.grid
                dfs.append(df)            
            else:
                raise ValueError("upscaling qc has become out of sync with metadata from fmu-tools")
        return pd.concat(dfs)



    def get_statistics(self) -> pd.DataFrame:
        for _, df in self._get_well_data().groupby("ZONE"):
            print(df)


    def to_disk(self, path: str = "../../share/results/tables/xxupscaling_qc") -> None:
        folder = Path(path)

        if not folder.parent.is_dir():
            print(f"Cannot create folder. Ensure that {folder.parent} exists.")
        folder.mkdir(exist_ok=True)
        print("Extracting data...")
        self._get_well_data().to_csv(folder / UpscalingQCFiles.WELLS, index=False)
        self._get_bw_data().to_csv(folder / UpscalingQCFiles.BLOCKEDWELLS, index=False)
        self._get_grid_data().to_csv(folder / UpscalingQCFiles.GRID, index=False)
        with open(folder / UpscalingQCFiles.METADATA, "w") as fp:
            json.dump(asdict(self._metadata), fp, indent=4)
        print(f"Done. Output written to {folder}.")
