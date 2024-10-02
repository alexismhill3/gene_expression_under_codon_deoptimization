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
final_positions = {'E4': ['C2', 'GFP10', 'R0.25', 19.383064579703888, 171.1169354202961], 'C5': ['D2', 'GFP10', 'R0.5', 21.19636498455252, 169.30363501544747], 'D4': ['E2', 'GFP10', 'R1', 25.563416213026102, 164.9365837869739], 'F3': ['F2', 'GFP10', 'R2', 19.98602262742471, 170.51397737257528], 'D3': ['G2', 'GFP10', 'R4', 17.896440532179973, 172.60355946782002], 'C3': ['C3', 'GFP25', 'R0.25', 16.168925432110637, 174.33107456788937], 'C4': ['D3', 'GFP25', 'R0.5', 18.628588857259835, 171.87141114274016], 'G2': ['E3', 'GFP25', 'R1', 17.463305902452557, 173.03669409754744], 'E6': ['F3', 'GFP25', 'R2', 22.220685981988865, 168.27931401801112], 'G4': ['G3', 'GFP25', 'R4', 18.576939334547262, 171.92306066545274], 'B3': ['C4', 'GFP50', 'R0.25', 18.26584066387065, 172.23415933612935], 'F6': ['D4', 'GFP50', 'R0.5', 21.23475267503508, 169.26524732496492], 'G6': ['E4', 'GFP50', 'R1', 21.4975470627281, 169.0024529372719], 'F2': ['F4', 'GFP50', 'R2', 18.66565945934993, 171.83434054065006], 'E5': ['G4', 'GFP50', 'R4', 18.459951685604608, 172.0400483143954], 'D6': ['C5', 'GFP75', 'R0.25', 20.376764837364394, 170.1232351626356], 'B6': ['D5', 'GFP75', 'R0.5', 17.463305902452557, 173.03669409754744], 'C6': ['E5', 'GFP75', 'R1', 16.824336073783115, 173.67566392621688], 'C2': ['F5', 'GFP75', 'R2', 16.884904599144335, 173.61509540085567], 'E2': ['G5', 'GFP75', 'R4', 17.535125927068258, 172.96487407293174], 'G3': ['C6', 'GFP90', 'R0.25', 16.866688661979374, 173.63331133802063], 'B4': ['D6', 'GFP90', 'R0.5', 18.998339098708872, 171.50166090129113], 'G5': ['E6', 'GFP90', 'R1', 18.20204098851399, 172.297959011486], 'D5': ['F6', 'GFP90', 'R2', 18.710335841454434, 171.78966415854558], 'B2': ['G6', 'GFP90', 'R4', 14.966716206532023, 175.53328379346797], 'F10': ['C7', 'GFP10', 'R0.25', 20.26232262869863, 170.23767737130137], 'E10': ['D7', 'GFP10', 'R0.5', 20.940838786528243, 169.55916121347175], 'E11': ['E7', 'GFP10', 'R1', 26.031638244784755, 164.46836175521526], 'D7': ['F7', 'GFP10', 'R2', 21.16766659968283, 169.33233340031717], 'G7': ['G7', 'GFP10', 'R4', 17.707252074240934, 172.79274792575907], 'C7': ['C8', 'GFP25', 'R0.25', 16.915352694218093, 173.5846473057819], 'E9': ['D8', 'GFP25', 'R0.5', 18.68052638336931, 171.8194736166307], 'E8': ['E8', 'GFP25', 'R1', 17.55481513426886, 172.94518486573114], 'C11': ['F8', 'GFP25', 'R2', 21.487699301623543, 169.01230069837646], 'G9': ['G8', 'GFP25', 'R4', 18.380373306906105, 172.1196266930939], 'G8': ['C9', 'GFP50', 'R0.25', 19.060105788299, 171.439894211701], 'F9': ['D9', 'GFP50', 'R0.5', 20.773886127241536, 169.72611387275848], 'G10': ['E9', 'GFP50', 'R1', 21.129520861480493, 169.3704791385195], 'B11': ['F9', 'GFP50', 'R2', 18.65081396988508, 171.84918603011494], 'C8': ['G9', 'GFP50', 'R4', 18.591667406493034, 171.90833259350697], 'F8': ['C10', 'GFP75', 'R0.25', 19.479669195442824, 171.02033080455718], 'B8': ['D10', 'GFP75', 'R0.5', 18.194980571342615, 172.30501942865737], 'D10': ['E10', 'GFP75', 'R1', 16.8424605954963, 173.6575394045037], 'D11': ['F10', 'GFP75', 'R2', 17.056841625584312, 173.4431583744157], 'F11': ['G10', 'GFP75', 'R4', 18.518261836385857, 171.98173816361415], 'B9': ['C11', 'GFP90', 'R0.25', 16.59220933004488, 173.90779066995512], 'B10': ['D11', 'GFP90', 'R0.5', 14.745558478364828, 175.75444152163516], 'C9': ['E11', 'GFP90', 'R1', 17.848765933268403, 172.6512340667316], 'D8': ['F11', 'GFP90', 'R2', 17.848765933268403, 172.6512340667316], 'F7': ['G11', 'GFP90', 'R4', 15.005023068359858, 175.49497693164014], 'D2': ['blank', 'blank', 'blank', 0, 190.5], 'E3': ['blank', 'blank', 'blank', 0, 190.5], 'F4': ['blank', 'blank', 'blank', 0, 190.5], 'B5': ['blank', 'blank', 'blank', 0, 190.5], 'F5': ['blank', 'blank', 'blank', 0, 190.5], 'B7': ['blank', 'blank', 'blank', 0, 190.5], 'E7': ['blank', 'blank', 'blank', 0, 190.5], 'D9': ['blank', 'blank', 'blank', 0, 190.5], 'C10': ['blank', 'blank', 'blank', 0, 190.5], 'G11': ['blank', 'blank', 'blank', 0, 190.5]}
iptg_volume = 9.5
metadata = {'protocolName': 'Burden_100124', 'author': 'Cameron <croots@utexas.edu>', 'description': 'Burden experiment on codon-specific strains', 'apiLevel': '2.18'}
induced_wells = ['B2', 'C2', 'D2', 'E2', 'F2', 'G2', 'B3', 'C3', 'D3', 'E3', 'F3', 'G3', 'B4', 'C4', 'D4', 'E4', 'F4', 'G4', 'B5', 'C5', 'D5', 'E5', 'F5', 'G5', 'B6', 'C6', 'D6', 'E6', 'F6', 'G6']
uninduced_wells = ['B7', 'C7', 'D7', 'E7', 'F7', 'G7', 'B8', 'C8', 'D8', 'E8', 'F8', 'G8', 'B9', 'C9', 'D9', 'E9', 'F9', 'G9', 'B10', 'C10', 'D10', 'E10', 'F10', 'G10', 'B11', 'C11', 'D11', 'E11', 'F11', 'G11']