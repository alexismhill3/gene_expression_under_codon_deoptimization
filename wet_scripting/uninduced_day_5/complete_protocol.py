from opentrons import protocol_api, types
from opentrons.protocol_api.labware import OutOfTipsError, Well, Labware, next_available_tip
from opentrons.protocol_api.instrument_context import InstrumentContext
from typing import Any, AnyStr, List, Dict, Optional, Union, Tuple, TYPE_CHECKING
import logging
import logging

from contextlib import suppress

# ---------- Protocol Setup

# requirements
requirements = {"robotType": "OT-2"}

# ---------- Custom Systems

class CustomPipette(InstrumentContext):
    """This is a wrapper to the Opentrons pipette classes that does two things.
    First, it changes the out of tips behavior to wait for you to replace the tips.
    Secondly, it enables multichannels to pick up individual tips.

    :param parent_instance: The parent pipette instance
    :param parent_protocol: The protocol context spawning this pipette"""
    def __init__(self, parent_instance, parent_protocol):
        vars(self).update(vars(parent_instance))
        self.protocol = parent_protocol

        if self.mount == 'left':
            checked_mount = types.Mount.LEFT
        if self.mount == 'right':
            checked_mount = types.Mount.RIGHT

        self.protocol._instruments[checked_mount] = self

    def pick_up_tip(self,
                    number: Optional[int] = 1,
                    **kwargs) -> InstrumentContext:
        """Wrapper of the pick up tip function. Prompts operator to refill tips and enables less-than-max
        tip collection by multichannel pipettes.

        :param number: number of tips to pick up (defaults to 1, errors >1 on single channels)

        See super().pick_up_tip for other paramaters"""

        # Bypass everything if operator tells speifically where to pick up a tip
        if kwargs.get('location'): # if location arg exists and is not none
            super().pick_up_tip(**kwargs)
            return self

        # Sanity checking for multichannels
        if not isinstance(number, int) or not 0 < number <= self.channels:
            raise ValueError(f"Invalid value for number of pipette channels: {number}")
        # @TODO: Check for deck conflicts when multichannels are picking up less than the max number of tips.

        # Check to see if there is enought tips for the pipette. If not, have the tips replaced.
        next_tip = None
        try:
            next_tip =  self.next_tip(number)
        except OutOfTipsError:
            input(f"Please replace the following tip boxes then press enter: {self.tip_racks}")
            super().reset_tipracks()

        if not next_tip:
            next_tip = self.next_tip(number)

        # Set the depression strength
        pipette_type = self.model
        if pipette_type == "p20_multi_gen2":
            pickup_current = 0.075
        else:
            pickup_current = 1
        pickup_current = pickup_current*number # of tips
        if self.mount == 'left':
            mountpoint = types.Mount.LEFT
        else:
            mountpoint = types.Mount.RIGHT

        # The doccumented way to actually change the pick up voltage is outdated
        # self.protocol._hw_manager.hardware._attached_instruments[mountpoint].update_config_item('pickupCurrent', pickup_current)

        # Overwrite the tip location (for multichannel pick ups less than max)
        kwargs['location'] = next_tip

        super().pick_up_tip(**kwargs)

        return self

    def next_tip(self, number_of_tips: int) -> Well:
        ''''''
        # Determine where the tips should be picked up from.
        target_well = None
        for tip_rack in self.tip_racks:
            truth_table = [[well.has_tip for well in column] for column in tip_rack.columns()]
            for i1, column in enumerate(tip_rack.columns()):
                for i2, _ in enumerate(column[::-1]):
                    well_index = 7-i2
                    if well_index+number_of_tips > 8:
                        continue
                    if all(truth_table[i1][well_index:well_index+number_of_tips]):
                        target_well = column[well_index]
                        break
                if target_well:
                    break
            if target_well:
                break
        else:
            raise OutOfTipsError
        return target_well

    def get_available_volume(self)-> float:
        "Returns the available space in the tip OR lower(max volume next tip, max volume pipette)"
        if self.has_tip:
            return self.max_volume - self.current_volume
        else:
            next_tip = self.next_tip(1)
            return min([next_tip.max_volume, self.max_volume])

    def get_current_volume(self)-> float:
        return self.current_volume

    def transfer(self, volume, source, destination, touch_tip=False, blow_out=False, reverse=False):
        aspiration_volume = volume
        despense_volume = volume

        if self.get_current_volume():
            self.dispense(self.get_current_volume(), source)

        if reverse and volume*1.1 <= self.get_available_volume():
            aspiration_volume = volume*1.1
        if aspiration_volume > self.get_available_volume():
            raise ValueError(f"Volume {aspiration_volume} is too large for the current tip. Available volume is {self.get_available_volume()}")

        self.aspirate(aspiration_volume, source)
        self.dispense(despense_volume, destination)
        if blow_out:
            self.blow_out(destination)
        if touch_tip:
            self.touch_tip(destination)

        return self.get_current_volume()



# ---------- Actual Protocol

# protocol run function
def run(protocol: protocol_api.ProtocolContext):
    protocol.home()
    # labware

    plate_1 = protocol.load_labware('nest_96_wellplate_200ul_flat', 4)
    plate_2 = protocol.load_labware('nest_96_wellplate_200ul_flat', 5)

    reagent_reservoir = protocol.load_labware('usascientific_12_reservoir_22ml', 6)
    lb_location = reagent_reservoir['A1'].bottom(5)
    iptg_location = reagent_reservoir['A3'].bottom(5)


    tiprack_300 = protocol.load_labware('opentrons_96_tiprack_300ul', 8)
    tiprack_20 = protocol.load_labware('opentrons_96_tiprack_20ul', 9)

    p300 = protocol.load_instrument('p300_single', "left", tip_racks=[tiprack_300])
    p20 = protocol.load_instrument('p20_multi_gen2', "right", tip_racks=[tiprack_20])

    p300 = CustomPipette(p300, protocol)
    p20 = CustomPipette(p20, protocol)

    # Define liquids

    lb = protocol.define_liquid(
    name="LB-Carb",
    description="LB + 1x Carbenicillin",
    display_color="#b58005",
    )
    reagent_reservoir['A1'].load_liquid(liquid=lb, volume=15000)
    iptg = protocol.define_liquid(
        name="LB-Carb-IPTG",
        description="LB + 1x Carbenicillin + IPTG",
        display_color="#83b505",
    )
    reagent_reservoir['A3'].load_liquid(liquid=iptg, volume=15000)

    # Set up dictionaries for cell volumes and LB
    lb_instructions = [(value[4], key)
                        for key, value in final_positions.items()] # Volume, Destination
    cell_instructions = [(value[3], value[0], key)
                         for key, value in final_positions.items()]  # Volume, Source, Destination
    locations = list(final_positions.keys())


    # Add LB
    p300.pick_up_tip(1)
    for lb_volume, destination in lb_instructions:  # Add LB to all relevant wells
        p300.transfer(lb_volume, lb_location, plate_2[destination], touch_tip=True, reverse=True)
    p300.drop_tip()

    # Add Cells
    for cell_volume, source, destination in cell_instructions:  # Add cells to all releveant wells
        if cell_volume > 10:
            pipette = p300
        else:
            pipette = p20
        if source == "blank":
            source = lb_location
        else:
            pipette.pick_up_tip(1)
            source = plate_1[source]

            pipette.transfer(cell_volume,
                            source,
                            plate_2[destination],
                            touch_tip=True,
                            reverse=True)
            pipette.drop_tip()

    # Induction
    induced_locations = [x for x in final_positions if x in induced_wells]
    uninduced_locations = [x for x in final_positions if x not in induced_wells]
    for i, (locations, iptg_source) in enumerate(zip((induced_locations, uninduced_locations), (iptg_location, lb_location))):
        if i == 0:
            protocol.comment("Inducing with iptg")
        else:
            protocol.comment("Inducing without IPTG")


        column_occupancy = {n: [False]*12 for n in range(1, 13)} # Logic for tip quantity and where to induce first
        letters = "ABCDEFGH"
        for location in locations:
            column_occupancy[int(location[1:])][letters.index(location[0])] = True
        for column in column_occupancy.keys():
            try:
                start_row = next(i for i, x in enumerate(column_occupancy[column]) if x)
                num_tips = sum(column_occupancy[column])
            except:
                start_row = 0
                num_tips = 0

            column_occupancy[column] = (start_row, num_tips, iptg_source)

        for column, (row, num_tips, iptg_source) in column_occupancy.items():  # Induce all wells
            if num_tips == 0:
                continue
            p20.pick_up_tip(num_tips)
            start_point = plate_2[str(letters[row]) + str(column)]
            p20.transfer((iptg_volume), iptg_source, start_point, touch_tip=True, reverse=True)
            p20.drop_tip()


    protocol.home()

final_positions = {}
iptg_volume = 0
induced_wells = []
uninduced_wells = []
# ---------- Appended Data
final_positions = {'D6': ['C2', 'GFP10', 'R0.25', 13.8777375165995, 176.6222624834005], 'F4': ['D2', 'GFP10', 'R0.5', 16.091814163887513, 174.4081858361125], 'F2': ['E2', 'GFP10', 'R1', 14.227142638846612, 176.2728573611534], 'F6': ['F2', 'GFP10', 'R2', 17.277388337785492, 173.22261166221452], 'C3': ['G2', 'GFP10', 'R4', 15.155819963629385, 175.3441800363706], 'B2': ['C3', 'GFP25', 'R0.25', 14.78786763947348, 175.7121323605265], 'D3': ['D3', 'GFP25', 'R0.5', 15.714401138453551, 174.78559886154645], 'G2': ['E3', 'GFP25', 'R1', 17.01414841536383, 173.48585158463618], 'F5': ['F3', 'GFP25', 'R2', 17.52922787204852, 172.97077212795148], 'C5': ['G3', 'GFP25', 'R4', 15.563180561231112, 174.93681943876888], 'B6': ['C4', 'GFP50', 'R0.25', 16.186222733764055, 174.31377726623595], 'D2': ['D4', 'GFP50', 'R0.5', 16.20299945746767, 174.29700054253232], 'E2': ['E4', 'GFP50', 'R1', 17.548903828856606, 172.9510961711434], 'F3': ['F4', 'GFP50', 'R2', 17.11347918905961, 173.3865208109404], 'B4': ['G4', 'GFP50', 'R4', 13.869529583785376, 176.63047041621462], 'C4': ['C5', 'GFP75', 'R0.25', 22.72785476876215, 167.77214523123786], 'C6': ['D5', 'GFP75', 'R0.5', 15.063334357812694, 175.4366656421873], 'D5': ['E5', 'GFP75', 'R1', 13.57644838734372, 176.92355161265627], 'E3': ['F5', 'GFP75', 'R2', 13.250424140085542, 177.24957585991444], 'D4': ['G5', 'GFP75', 'R4', 12.418895659495716, 178.08110434050428], 'B5': ['C6', 'GFP90', 'R0.25', 12.742813482781473, 177.7571865172185], 'C2': ['D6', 'GFP90', 'R0.5', 14.069234494599595, 176.43076550540042], 'G4': ['E6', 'GFP90', 'R1', 15.131372252148184, 175.3686277478518], 'G5': ['F6', 'GFP90', 'R2', 13.76370444749255, 176.73629555250744], 'E4': ['G6', 'GFP90', 'R4', 13.521651222357342, 176.97834877764265], 'E10': ['C7', 'GFP10', 'R0.25', 15.62019633775193, 174.87980366224807], 'B8': ['D7', 'GFP10', 'R0.5', 16.304386252275215, 174.1956137477248], 'D8': ['E7', 'GFP10', 'R1', 14.331479546209982, 176.16852045379002], 'B10': ['F7', 'GFP10', 'R2', 17.938193970449976, 172.56180602955], 'D10': ['G7', 'GFP10', 'R4', 14.924330703668037, 175.57566929633197], 'G11': ['C8', 'GFP25', 'R0.25', 15.204953155468981, 175.29504684453102], 'B11': ['D8', 'GFP25', 'R0.5', 15.594227250168313, 174.9057727498317], 'G10': ['E8', 'GFP25', 'R1', 17.601590299511212, 172.8984097004888], 'C11': ['F8', 'GFP25', 'R2', 17.56862400647386, 172.93137599352613], 'F10': ['G8', 'GFP25', 'R4', 15.30418296478777, 175.19581703521223], 'E11': ['C9', 'GFP50', 'R0.25', 20.646769740296627, 169.85323025970337], 'G8': ['D9', 'GFP50', 'R0.5', 16.113927661986054, 174.38607233801395], 'D9': ['E9', 'GFP50', 'R1', 17.36695449654471, 173.1330455034553], 'E9': ['F9', 'GFP50', 'R2', 17.52267772023051, 172.97732227976948], 'G9': ['G9', 'GFP50', 'R4', 14.309617062526382, 176.19038293747363], 'F9': ['C10', 'GFP75', 'R0.25', 23.373467210332077, 167.12653278966792], 'C9': ['D10', 'GFP75', 'R0.5', 15.160718404806484, 175.3392815951935], 'B7': ['E10', 'GFP75', 'R1', 13.440279878437094, 177.05972012156292], 'F7': ['F10', 'GFP75', 'R2', 13.83271432521209, 176.6672856747879], 'D11': ['G10', 'GFP75', 'R4', 12.585520518866716, 177.9144794811333], 'E8': ['C11', 'GFP90', 'R0.25', 12.548480387584565, 177.95151961241544], 'F11': ['D11', 'GFP90', 'R0.5', 14.002030239800966, 176.49796976019903], 'D7': ['E11', 'GFP90', 'R1', 14.986323579616665, 175.51367642038335], 'B9': ['F11', 'GFP90', 'R2', 14.626457577239691, 175.8735424227603], 'C10': ['G11', 'GFP90', 'R4', 13.467294623022758, 177.03270537697725], 'B3': ['blank', 'blank', 'blank', 0, 190.5], 'G3': ['blank', 'blank', 'blank', 0, 190.5], 'E5': ['blank', 'blank', 'blank', 0, 190.5], 'E6': ['blank', 'blank', 'blank', 0, 190.5], 'G6': ['blank', 'blank', 'blank', 0, 190.5], 'C7': ['blank', 'blank', 'blank', 0, 190.5], 'E7': ['blank', 'blank', 'blank', 0, 190.5], 'G7': ['blank', 'blank', 'blank', 0, 190.5], 'C8': ['blank', 'blank', 'blank', 0, 190.5], 'F8': ['blank', 'blank', 'blank', 0, 190.5]}
iptg_volume = 9.5
metadata = {'protocolName': 'Burden_093024', 'author': 'Cameron <croots@utexas.edu>', 'description': 'Burden experiment on codon-specific strains', 'apiLevel': '2.18'}
induced_wells = ['B2', 'C2', 'D2', 'E2', 'F2', 'G2', 'B3', 'C3', 'D3', 'E3', 'F3', 'G3', 'B4', 'C4', 'D4', 'E4', 'F4', 'G4', 'B5', 'C5', 'D5', 'E5', 'F5', 'G5', 'B6', 'C6', 'D6', 'E6', 'F6', 'G6']
uninduced_wells = ['B7', 'C7', 'D7', 'E7', 'F7', 'G7', 'B8', 'C8', 'D8', 'E8', 'F8', 'G8', 'B9', 'C9', 'D9', 'E9', 'F9', 'G9', 'B10', 'C10', 'D10', 'E10', 'F10', 'G10', 'B11', 'C11', 'D11', 'E11', 'F11', 'G11']
