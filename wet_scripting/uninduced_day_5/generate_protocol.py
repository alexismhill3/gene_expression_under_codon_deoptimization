# import opentrons.simulate
import os
from rich import print
import random
import pandas as pd
import re

protocol_file = "complete_protocol.py"
experiment_date = "093024"
pre_data = f"cr_{experiment_date}_pre.csv"
iptg_volume = 9.5
random.seed(pre_data)

metadata = {
    "protocolName": f"Burden_{experiment_date}",
    "author": "Cameron <croots@utexas.edu>",
    "description": "Burden experiment on codon-specific strains",
    "apiLevel": "2.18",
}

#[CDS, RBS, isInduced]
cell_locations = {
    'B2': ['blank', 'blank', True],
    'C2': ['GFP10', 'R0.25', True],
    'D2': ['GFP10', 'R0.5', True],
    'E2': ['GFP10', 'R1', True],
    'F2': ['GFP10', 'R2', True],
    'G2': ['GFP10', 'R4', True],

    'B3': ['blank', 'blank', True],
    'C3': ['GFP25', 'R0.25', True],
    'D3': ['GFP25', 'R0.5', True],
    'E3': ['GFP25', 'R1', True],
    'F3': ['GFP25', 'R2', True],
    'G3': ['GFP25', 'R4', True],

    'B4': ['blank', 'blank', True],
    'C4': ['GFP50', 'R0.25', True],
    'D4': ['GFP50', 'R0.5', True],
    'E4': ['GFP50', 'R1', True],
    'F4': ['GFP50', 'R2', True],
    'G4': ['GFP50', 'R4', True],

    'B5': ['blank', 'blank', True],
    'C5': ['GFP75', 'R0.25', True],
    'D5': ['GFP75', 'R0.5', True],
    'E5': ['GFP75', 'R1', True],
    'F5': ['GFP75', 'R2', True],
    'G5': ['GFP75', 'R4', True],

    'B6': ['blank', 'blank', True],
    'C6': ['GFP90', 'R0.25', True],
    'D6': ['GFP90', 'R0.5', True],
    'E6': ['GFP90', 'R1', True],
    'F6': ['GFP90', 'R2', True],
    'G6': ['GFP90', 'R4', True],

    'B7': ['blank', 'blank', False],
    'C7': ['GFP10', 'R0.25', False],
    'D7': ['GFP10', 'R0.5', False],
    'E7': ['GFP10', 'R1', False],
    'F7': ['GFP10', 'R2', False],
    'G7': ['GFP10', 'R4', False],

    'B8': ['blank', 'blank', False],
    'C8': ['GFP25', 'R0.25', False],
    'D8': ['GFP25', 'R0.5', False],
    'E8': ['GFP25', 'R1', False],
    'F8': ['GFP25', 'R2', False],
    'G8': ['GFP25', 'R4', False],

    'B9': ['blank', 'blank', False],
    'C9': ['GFP50', 'R0.25', False],
    'D9': ['GFP50', 'R0.5', False],
    'E9': ['GFP50', 'R1', False],
    'F9': ['GFP50', 'R2', False],
    'G9': ['GFP50', 'R4', False],

    'B10': ['blank', 'blank', False],
    'C10': ['GFP75', 'R0.25', False],
    'D10': ['GFP75', 'R0.5', False],
    'E10': ['GFP75', 'R1', False],
    'F10': ['GFP75', 'R2', False],
    'G10': ['GFP75', 'R4', False],

    'B11': ['blank', 'blank', False],
    'C11': ['GFP90', 'R0.25', False],
    'D11': ['GFP90', 'R0.5', False],
    'E11': ['GFP90', 'R1', False],
    'F11': ['GFP90', 'R2', False],
    'G11': ['GFP90', 'R4', False],

}


# Assign each preconditioning to two experimental wells
def assign_wells(cell_locations):
    valid_rows = list("BCDEFG")
    valid_columns = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]

    valid_wells = [f"{row}{column}" for column in valid_columns for row in valid_rows]
    num_induced_wells = sum([True if x[2] else False for x in cell_locations.values()])
    induced_wells = valid_wells[:num_induced_wells]
    uninduced_wells = valid_wells[num_induced_wells:]

    wells_with_cells = [
        well for well in cell_locations if cell_locations[well][0] != "blank"
    ]

    final_positions = {}

    for well in wells_with_cells:
        if cell_locations[well][2]:
            tgt_wells = induced_wells
        else:
            tgt_wells = uninduced_wells

        position_1 = random.choice(tgt_wells)
        position_1_index = tgt_wells.index(position_1)
        del tgt_wells[position_1_index]

        final_positions[position_1] = [
            well,
            cell_locations[well][0],
            cell_locations[well][1],
        ]

    # Fill the rest of the valid positions with blanks

    for well in valid_wells:
        final_positions[well] = final_positions.get(well, ["blank", "blank", "blank"])

    induced_wells = valid_wells[:num_induced_wells]
    uninduced_wells = valid_wells[num_induced_wells:]

    return final_positions, induced_wells, uninduced_wells


def parse_platereader(filename):
    """Parse the output of a Teccan plate reader and make the data tidy"""
    with open(filename, "r") as file:
        lines = file.readlines()
    lines = [line.strip() for line in lines]
    dataframe = pd.DataFrame(columns=["time", "well", "label", "value", "temperature"])
    datasets = []
    reading_dataset = [None, None]
    start_time = None
    for i, line in enumerate(lines):
        line = line.split(",")
        if line[0].startswith("End Time:"):
            continue
        elif line[0].startswith("Start Time:"):
            start_time = i
        elif start_time and any(line) > 0 and not any(reading_dataset):
            reading_dataset[0] = i
        elif start_time and any(line) == 0 and any(reading_dataset):
            reading_dataset[1] = i  # Exclusive
            datasets.append(reading_dataset)
            reading_dataset = [None, None]

    def filter_function(test_value):
        if test_value == "":
            return False
        else:
            return True

    for dataset in datasets:
        data = lines[dataset[0] : dataset[1]]
        label = data.pop(0).split(",")[0]

        if data[0].startswith("Cycle"):
            cycle = data.pop(0).split(",")[1:]

        times = list(filter(filter_function, data.pop(0).split(",")[1:]))
        temperature = list(filter(filter_function, data.pop(0).split(",")[1:]))
        data = list(filter(filter_function, [line.split(",") for line in data]))

        for line in data:
            well = str(line.pop(0))
            line = list(filter(filter_function, line))
            for i, value in enumerate(line):
                adding_frame = pd.DataFrame(
                    {
                        "time": round(float(times[i])),
                        "well": well,
                        "label": label,
                        "value": float(value),
                        "temperature": float(temperature[i]),
                    },
                    index=[0],
                )

                dataframe = pd.concat([dataframe, adding_frame])
    return dataframe


def normalize_values(platereader_file):
    platereader_data = parse_platereader(platereader_file)

    target_OD660 = (
        0.0234506  # This is equivilant to 0.2 OD600 on our 1cm spectrophotometer
    )

    blank_wells = [x for x in cell_locations.keys() if "blank" in cell_locations[x]]

    cell_volumes = {}
    lb_volumes = {}


    # Get the latest timepoint from the platereader data
    latest_timepoint = platereader_data["time"].max()

    # Set the OD660 column to be a float

    # Get the latest OD660 values for the blank wells
    blank_OD660 = platereader_data.loc[
        (platereader_data["time"] == latest_timepoint)
        & (platereader_data["well"].isin(blank_wells))
        & (platereader_data.label.isin(["OD660"])),
        "value",
    ].mean()


    # Get all the wells that are used in the protocol
    occupied_wells = platereader_data.loc[
        (platereader_data["time"] == latest_timepoint)
        & (platereader_data.label.isin(["OD660"])),
        "well",
    ]

    # Remove the blank wells
    occupied_wells = [well for well in occupied_wells if well not in blank_wells]

    for start_well in occupied_wells:
        well_OD660 = platereader_data.loc[
            (platereader_data["time"] == latest_timepoint)
            & (platereader_data["well"] == start_well)
            & (platereader_data.label.isin(["OD660"])),
            "value",
        ].mean()
        well_OD660 = well_OD660 - blank_OD660

        cell_volume = (target_OD660 / well_OD660) * 200
        if cell_volume > (200 - iptg_volume):
            cell_volume = 200 - iptg_volume
        if cell_volume < 0:
            cell_volume = 0
        lb_volume = (200 - iptg_volume) - cell_volume

        cell_volumes[start_well] = [start_well, cell_volume]
        lb_volumes[start_well] = lb_volume

    return cell_volumes, lb_volumes


def apply_values(final_positions, cell_volumes, lb_volumes):
    for well in final_positions:
        source_well = final_positions[well][0]
        if source_well == "blank":
            final_positions[well].append(0)
            final_positions[well].append((200 - iptg_volume))
        else:
            final_positions[well].append(cell_volumes[source_well][1])
            final_positions[well].append(lb_volumes[source_well])

    return final_positions


def create_protocol(final_positions, induced_wells, uninduced_wells):
    # Make a copy of base_protocol.py and name it complete_protocol.py
    os.system("cp base_protocol_multichannel.py complete_protocol.py")

    # Add the volumes to the complete_protocol.py file
    with open("complete_protocol.py", "a") as file:
        file.write(f"final_positions = {final_positions}\n")
        file.write(f"iptg_volume = {iptg_volume}\n")
        file.write(f"metadata = {metadata}\n")
        file.write(f"induced_wells = {induced_wells}\n")
        file.write(f"uninduced_wells = {uninduced_wells}\n")

    # Simulate the protocol
    # opentrons.simulate.simulate(open(protocol_file))


final_positions, induced_wells, uninduced_wells = assign_wells(cell_locations)
cell_volumes, lb_volumes = normalize_values(pre_data)
final_positions = apply_values(final_positions, cell_volumes, lb_volumes)
create_protocol(final_positions, induced_wells, uninduced_wells)
