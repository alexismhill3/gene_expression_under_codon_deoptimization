#include <cmath>
#include <fstream>
#include <iostream>

#include "choices.hpp"
#include "model.hpp"
#include "polymer.hpp"
#include "tracker.hpp"

Model::Model(double cell_volume) : cell_volume_(cell_volume) {
  auto &tracker = SpeciesTracker::Instance();
  tracker.Clear();
  gillespie_ = Gillespie();
  tracker.propensity_signal_.ConnectMember(&gillespie_,
                                           &Gillespie::UpdatePropensity);
}

void Model::seed(int seed) { Random::seed(seed); }

void Model::Simulate(int time_limit, double time_step,
                     const std::string &output = "counts.tsv") {
  auto &tracker = SpeciesTracker::Instance();
  Initialize();
  // Set up file output streams
  std::ofstream countfile(output, std::ios::trunc);
  // Output header
  countfile << "time\tspecies\tprotein\ttranscript\tribo_density\tcollisions\n";
  double out_time = 0.0;
  while (gillespie_.time() < time_limit) {
    if ((out_time - gillespie_.time()) < 0.001) {
      countfile << tracker.GatherCounts(gillespie_.time());
      countfile.flush();
      tracker.ResetCollision();
      out_time += time_step;
    }
    gillespie_.Iterate();
  }
  countfile.close();
  std::cout << "Simulation successful. Ignore any warnings that follow." << std::endl;
}

//void Model::AddtRNA(const CodonMap &codons, double rate_constant) {
void Model::AddtRNA(std::map<std::string, std::map<std::string, std::map<std::string, int>>> &codons, double rate_constant) {
  /** Steps
   * 1. Add charged and uncharged tRNA species to the species tracker
   * 2. Define reactions for tRNA charging (eventually this could be an aggregate reaction)
   * 3. Actual codon map also should be added to the species tracker
   */
  auto &tracker = SpeciesTracker::Instance();
  std::map<std::string, std::vector<std::string>> codon_map;
  for (auto const& codon : codons) {
    codon_map[codon.first] = std::vector<std::string>();
    for (auto const& anticodon : codon.second) {
      tracker.Increment(anticodon.first + "_charged", anticodon.second.find("charged")->second);
      tracker.Increment(anticodon.first + "_uncharged", anticodon.second.find("uncharged")->second);
      AddtRNAReaction(rate_constant, {anticodon.first + "_uncharged"}, {anticodon.first + "_charged"});
      codon_map[codon.first].push_back(anticodon.first);
    }
  }
  tracker.codon_map(codon_map);
}

void Model::AddtRNA(std::map<std::string, std::vector<std::string>> &codon_map, 
                    std::map<std::string, std::pair<int, int>> &counts, 
                    std::map<std::string, double> &rate_constants) {
  auto &tracker = SpeciesTracker::Instance();
  for (auto const& trna : counts) {
    // Add initial charged tRNA species
    tracker.Increment(trna.first + "_charged", trna.second.first);
    // Add initial uncharged tRNA species
    tracker.Increment(trna.first + "_uncharged", trna.second.second);
    double rate_constant = rate_constants.find(trna.first)->second;
    AddtRNAReaction(rate_constant, {trna.first + "_uncharged"}, {trna.first + "_charged"});
  }
  tracker.codon_map(codon_map);
}

void Model::AddReaction(double rate_constant,
                        const std::vector<std::string> &reactants,
                        const std::vector<std::string> &products) {
  auto rxn = std::make_shared<SpeciesReaction>(rate_constant, cell_volume_,
                                               reactants, products);
  auto &tracker = SpeciesTracker::Instance();
  for (const auto &reactant : reactants) {
    tracker.Add(reactant, rxn);
  }
  for (const auto &product : products) {
    tracker.Add(product, rxn);
  }
  gillespie_.LinkReaction(rxn);
}

void Model::AddtRNAReaction(double rate_constant,
                        const std::vector<std::string> &reactants,
                        const std::vector<std::string> &products) {
  auto rxn = std::make_shared<SpeciesReaction>(rate_constant, cell_volume_,
                                               reactants, products);
  rxn->mark_tRNA(); // this reaction impacts tRNA pools
  auto &tracker = SpeciesTracker::Instance();
  for (const auto &reactant : reactants) {
    tracker.Add(reactant, rxn);
  }
  for (const auto &product : products) {
    tracker.Add(product, rxn);
  }
  gillespie_.LinkReaction(rxn);
}

void Model::AddSpecies(const std::string &name, int copy_number) {
  if (name.substr(0, 2) == "__") {
    throw std::invalid_argument(
        "Names prefixed with '__' (double underscore) are reserved for "
        "internal use.");
  }
  auto &tracker = SpeciesTracker::Instance();
  tracker.Increment(name, copy_number);
}

void Model::AddPolymerase(const std::string &name, int footprint,
                          double speed, int copy_number) {
  auto pol = Polymerase(name, footprint, speed);
  polymerases_.push_back(pol);
  auto &tracker = SpeciesTracker::Instance();
  tracker.Increment(name, copy_number);
  tracker.InitializeCollision(name);
}

void Model::AddRibosome(int footprint, double speed, int copy_number) {
  auto pol = Polymerase("__ribosome", footprint, speed);
  polymerases_.push_back(pol);
  auto &tracker = SpeciesTracker::Instance();
  tracker.Increment("__ribosome", copy_number);
  tracker.InitializeCollision("__ribosome");
}

void Model::RegisterPolymer(Polymer::Ptr polymer) {
  // Encapsulate polymer in PolymerWrapper reaction and add to reaction list
  auto wrapper = std::make_shared<PolymerWrapper>(polymer);
  polymer->wrapper(wrapper);
  gillespie_.LinkReaction(wrapper);
}

void Model::RegisterGenome(Genome::Ptr genome) {
  RegisterPolymer(genome);
  genome->termination_signal_.ConnectMember(
      &SpeciesTracker::Instance(), &SpeciesTracker::TerminateTranscription);
  genome->transcript_signal_.ConnectMember(this, &Model::RegisterTranscript);
  genomes_.push_back(genome);
}

void Model::RegisterTranscript(Transcript::Ptr transcript) {
  RegisterPolymer(transcript);
  transcript->termination_signal_.ConnectMember(
      &SpeciesTracker::Instance(), &SpeciesTracker::TerminateTranslation);
  if (initialized_ == false) {
    transcripts_.push_back(transcript);
  }
}

void Model::Initialize() {
  if (genomes_.size() == 0 && transcripts_.size() == 0) {
    std::cerr << "Warning: There are no Genome objects registered with "
                 "Model. Did you forget to register a Genome?"
              << std::endl;
  }
  // Create Bind reactions for each promoter-polymerase pair
  for (Genome::Ptr genome : genomes_) {
    for (auto promoter_name : genome->bindings()) {
      for (auto pol : polymerases_) {
        if (promoter_name.second.count(pol.name()) != 0) {
          double rate_constant = promoter_name.second[pol.name()];
          Polymerase pol_template = Polymerase(pol);
          auto reaction = std::make_shared<BindPolymerase>(
              rate_constant, cell_volume_, promoter_name.first, pol_template);
          auto &tracker = SpeciesTracker::Instance();
          tracker.Add(promoter_name.first, reaction);
          tracker.Add(pol.name(), reaction);
          gillespie_.LinkReaction(reaction);
        }
      }
    }
    // Create reaction for external rnase binding
    if (genome->transcript_degradation_rate_ext() != 0.0) {
      auto rnase_template_ext =
          Rnase(genome->rnase_footprint(), genome->rnase_speed());
      auto reaction_ext = std::make_shared<BindRnase>(
          genome->transcript_degradation_rate_ext(), cell_volume_,
          rnase_template_ext, "__rnase_site_ext");
      auto &tracker = SpeciesTracker::Instance();
      tracker.Add("__rnase_site_ext", reaction_ext);
      gillespie_.LinkReaction(reaction_ext);
    }
    
    // Create reaction for internal rnase binding
    if (genome->transcript_degradation_rate() != 0.0) {
      // TODO: user defined Rnase speed
      // auto rnase_template = Rnase(10, 30);
      auto rnase_template =
          Rnase(genome->rnase_footprint(), genome->rnase_speed());
      auto reaction = std::make_shared<BindRnase>(
          genome->transcript_degradation_rate(), cell_volume_, rnase_template,
          "__rnase_site");
      auto &tracker = SpeciesTracker::Instance();
      tracker.Add("__rnase_site", reaction);
      gillespie_.LinkReaction(reaction);
    } 
    
    // Alternatively, create bind reactions for individual rnase sites
    else if (genome->rnase_bindings().size() != 0) {
      for (auto rnase_site : genome->rnase_bindings()) {
        auto rnase_template =
          Rnase(genome->rnase_footprint(), genome->rnase_speed());
        auto reaction = std::make_shared<BindRnase>(
          rnase_site.second, cell_volume_, rnase_template, rnase_site.first);
        auto &tracker = SpeciesTracker::Instance();
        tracker.Add(rnase_site.first, reaction);
        gillespie_.LinkReaction(reaction);
      }
    }
  }
  
  // Initialize transcripts that have been defined independently of genome
  for (Transcript::Ptr transcript : transcripts_) {
    for (auto rbs_name : transcript->bindings()) {
      for (auto pol : polymerases_) {
        if (rbs_name.second.count(pol.name()) != 0) {
          double rate_constant = rbs_name.second[pol.name()];
          Polymerase pol_template = Polymerase(pol);
          auto reaction = std::make_shared<BindPolymerase>(
              rate_constant, cell_volume_, rbs_name.first, pol_template);
          auto &tracker = SpeciesTracker::Instance();
          tracker.Add(rbs_name.first, reaction);
          tracker.Add(pol.name(), reaction);
          gillespie_.LinkReaction(reaction);
        }
      }
    }
  }

  initialized_ = true;
}

void Model::CountTermination(const std::string &name) {
  auto new_name = name + "_total";
  if (terminations_.count(name) == 0) {
    terminations_[new_name] = 1;
  } else {
    terminations_[new_name]++;
  }
}
